package service

import (
	"strings"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

func (s *ClientService) SyncInbound(tx *gorm.DB, inboundId int, clients []model.Client) error {
	return s.syncInboundClients(tx, inboundId, clients, nil, true)
}

// ApplyInboundClientDelta persists only the clients an edit actually changed
// plus the emails it detached, leaving every other link on the inbound alone —
// the whole point being that a one-client edit must not rewrite the inbound's
// entire membership set (#6252).
func (s *ClientService) ApplyInboundClientDelta(tx *gorm.DB, inboundId int, changed []model.Client, detachEmails []string) error {
	return s.syncInboundClients(tx, inboundId, changed, detachEmails, false)
}

func (s *ClientService) syncInboundClients(tx *gorm.DB, inboundId int, clients []model.Client, detachEmails []string, prune bool) error {
	if tx == nil {
		tx = database.GetDB()
	}

	emails := make([]string, 0, len(clients))
	seen := make(map[string]struct{}, len(clients))
	for i := range clients {
		email := strings.TrimSpace(clients[i].Email)
		if email == "" {
			continue
		}
		if _, ok := seen[email]; ok {
			continue
		}
		seen[email] = struct{}{}
		emails = append(emails, email)
	}

	existing := make(map[string]*model.ClientRecord, len(emails))
	const selectChunk = 400
	for start := 0; start < len(emails); start += selectChunk {
		end := min(start+selectChunk, len(emails))
		var rows []model.ClientRecord
		if err := tx.Where("email IN ?", emails[start:end]).Find(&rows).Error; err != nil {
			return err
		}
		for i := range rows {
			r := rows[i]
			existing[r.Email] = &r
		}
	}

	idByEmail := make(map[string]int, len(emails))
	pending := make(map[string]*model.ClientRecord, len(emails))
	toCreate := make([]*model.ClientRecord, 0, len(emails))
	for i := range clients {
		email := strings.TrimSpace(clients[i].Email)
		if email == "" {
			continue
		}

		incoming := clients[i].ToRecord()
		// ToRecord copies the raw email; store the trimmed key this function
		// looks up by, or a padded email is inserted and never found again.
		incoming.Email = email
		row, ok := existing[email]
		if !ok {
			if _, dup := pending[email]; !dup {
				pending[email] = incoming
				toCreate = append(toCreate, incoming)
			}
			continue
		}

		before := *row
		if incoming.UUID != "" {
			row.UUID = incoming.UUID
		}
		if incoming.Password != "" {
			row.Password = incoming.Password
		}
		if incoming.Auth != "" {
			row.Auth = incoming.Auth
		}
		row.Flow = incoming.Flow
		if incoming.Security != "" {
			row.Security = incoming.Security
		}
		if incoming.Reverse != "" {
			row.Reverse = incoming.Reverse
		}
		row.SubID = incoming.SubID
		row.LimitIP = incoming.LimitIP
		row.HwidLimit = incoming.HwidLimit
		row.TotalGB = incoming.TotalGB
		row.ExpiryTime = incoming.ExpiryTime
		row.Enable = incoming.Enable
		row.TgID = incoming.TgID
		if incoming.Group != "" {
			row.Group = incoming.Group
		}
		row.Comment = incoming.Comment
		row.Reset = incoming.Reset
		if incoming.CreatedAt > 0 && (row.CreatedAt == 0 || incoming.CreatedAt < row.CreatedAt) {
			row.CreatedAt = incoming.CreatedAt
		}
		preservedUpdatedAt := max(incoming.UpdatedAt, row.UpdatedAt)
		row.UpdatedAt = preservedUpdatedAt

		idByEmail[email] = row.Id

		if *row == before {
			continue
		}
		if err := tx.Save(row).Error; err != nil {
			return err
		}
		if err := tx.Model(&model.ClientRecord{}).
			Where("id = ?", row.Id).
			UpdateColumn("updated_at", preservedUpdatedAt).Error; err != nil {
			return err
		}
	}

	if len(toCreate) > 0 {
		// Capture enable before Create: gorm default:true drops explicit false (#6478).
		// Restate disabled rows after CreateInBatches.
		wantEnable := make([]bool, len(toCreate))
		for i, rec := range toCreate {
			wantEnable[i] = rec.Enable
		}
		if err := tx.CreateInBatches(toCreate, 200).Error; err != nil {
			return err
		}
		disabledIDs := make([]int, 0)
		for i, rec := range toCreate {
			idByEmail[rec.Email] = rec.Id
			if !wantEnable[i] {
				disabledIDs = append(disabledIDs, rec.Id)
			}
		}
		for _, batch := range chunkInts(disabledIDs, sqlInChunk) {
			if err := tx.Model(&model.ClientRecord{}).Where("id IN ?", batch).
				UpdateColumn("enable", false).Error; err != nil {
				return err
			}
		}
	}

	wantedFlow := make(map[int]string, len(clients))
	wantedIds := make([]int, 0, len(clients))
	for i := range clients {
		email := strings.TrimSpace(clients[i].Email)
		if email == "" {
			continue
		}
		id, ok := idByEmail[email]
		if !ok {
			continue
		}
		if _, dup := wantedFlow[id]; dup {
			continue
		}
		wantedFlow[id] = clients[i].Flow
		wantedIds = append(wantedIds, id)
	}

	return s.reconcileInboundLinks(tx, inboundId, wantedFlow, wantedIds, detachEmails, prune)
}

// reconcileInboundLinks writes only the client_inbounds rows that differ. prune
// also removes links absent from wantedFlow, which only a full sync may do.
func (s *ClientService) reconcileInboundLinks(tx *gorm.DB, inboundId int, wantedFlow map[int]string, wantedIds []int, detachEmails []string, prune bool) error {
	var current []model.ClientInbound
	if prune {
		if err := tx.Where("inbound_id = ?", inboundId).Find(&current).Error; err != nil {
			return err
		}
	} else {
		for _, batch := range chunkInts(wantedIds, sqlInChunk) {
			var rows []model.ClientInbound
			if err := tx.Where("inbound_id = ? AND client_id IN ?", inboundId, batch).Find(&rows).Error; err != nil {
				return err
			}
			current = append(current, rows...)
		}
	}

	var toDelete []int
	toUpdate := make(map[string][]int)
	have := make(map[int]struct{}, len(current))
	for _, link := range current {
		have[link.ClientId] = struct{}{}
		flow, keep := wantedFlow[link.ClientId]
		if !keep {
			if prune {
				toDelete = append(toDelete, link.ClientId)
			}
			continue
		}
		// Plain compare, not non-empty-wins: clearing a flow must persist "".
		if flow != link.FlowOverride {
			toUpdate[flow] = append(toUpdate[flow], link.ClientId)
		}
	}

	if len(detachEmails) > 0 {
		for _, batch := range chunkStrings(detachEmails, sqlInChunk) {
			var ids []int
			if err := tx.Model(&model.ClientRecord{}).Where("email IN ?", batch).Pluck("id", &ids).Error; err != nil {
				return err
			}
			for _, id := range ids {
				if _, keep := wantedFlow[id]; !keep {
					toDelete = append(toDelete, id)
				}
			}
		}
	}

	toInsert := make([]model.ClientInbound, 0, len(wantedIds))
	for _, id := range wantedIds {
		if _, exists := have[id]; exists {
			continue
		}
		toInsert = append(toInsert, model.ClientInbound{
			ClientId:     id,
			InboundId:    inboundId,
			FlowOverride: wantedFlow[id],
		})
	}

	for _, batch := range chunkInts(toDelete, sqlInChunk) {
		if err := tx.Where("inbound_id = ? AND client_id IN ?", inboundId, batch).
			Delete(&model.ClientInbound{}).Error; err != nil {
			return err
		}
	}
	for flow, ids := range toUpdate {
		for _, batch := range chunkInts(ids, sqlInChunk) {
			if err := tx.Model(&model.ClientInbound{}).
				Where("inbound_id = ? AND client_id IN ?", inboundId, batch).
				Update("flow_override", flow).Error; err != nil {
				return err
			}
		}
	}
	if len(toInsert) > 0 {
		// The delete this replaced also serialized concurrent syncs of one
		// inbound; without the clause a racing node poll aborts its whole tx.
		if err := tx.Clauses(clause.OnConflict{
			Columns:   []clause.Column{{Name: "client_id"}, {Name: "inbound_id"}},
			DoUpdates: clause.AssignmentColumns([]string{"flow_override"}),
		}).CreateInBatches(toInsert, 200).Error; err != nil {
			return err
		}
	}
	return nil
}

func (s *ClientService) DetachInbound(tx *gorm.DB, inboundId int) error {
	if tx == nil {
		tx = database.GetDB()
	}
	return tx.Where("inbound_id = ?", inboundId).Delete(&model.ClientInbound{}).Error
}

func (s *ClientService) ListForInbound(tx *gorm.DB, inboundId int) ([]model.Client, error) {
	if tx == nil {
		tx = database.GetDB()
	}
	type joinedRow struct {
		model.ClientRecord
		FlowOverride string
	}
	var rows []joinedRow
	err := tx.Table("clients").
		Select("clients.*, client_inbounds.flow_override AS flow_override").
		Joins("JOIN client_inbounds ON client_inbounds.client_id = clients.id").
		Where("client_inbounds.inbound_id = ?", inboundId).
		Order("clients.id ASC").
		Find(&rows).Error
	if err != nil {
		return nil, err
	}

	out := make([]model.Client, 0, len(rows))
	for i := range rows {
		c := rows[i].ToClient()
		c.Flow = rows[i].FlowOverride
		out = append(out, *c)
	}
	return out, nil
}
