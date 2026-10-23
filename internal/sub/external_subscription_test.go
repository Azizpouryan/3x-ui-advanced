package sub

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestDoFetchSubscriptionLinks_RejectsOversizedBody(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(strings.Repeat("a", subscriptionMaxBytes+1)))
	}))
	defer srv.Close()

	links, err := doFetchSubscriptionLinks(srv.URL)
	if err != errSubscriptionBodyTooLarge {
		t.Fatalf("err = %v, want errSubscriptionBodyTooLarge", err)
	}
	if links != nil {
		t.Fatalf("links = %v, want nil", links)
	}
}

func TestDoFetchSubscriptionLinks_AcceptsBodyAtLimit(t *testing.T) {
	link := "vless://example"
	body := link + "\n" + strings.Repeat("#", subscriptionMaxBytes-len(link)-1)
	if len(body) != subscriptionMaxBytes {
		t.Fatalf("fixture size = %d, want %d", len(body), subscriptionMaxBytes)
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(body))
	}))
	defer srv.Close()

	links, err := doFetchSubscriptionLinks(srv.URL)
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if len(links) != 1 || links[0] != link {
		t.Fatalf("links = %v, want [%q]", links, link)
	}
}

func TestRecordExternalSubscriptionFetchStampsEveryRowForTheURL(t *testing.T) {
	initMutDB(t)
	resetSubscriptionCache(t)
	db := database.GetDB()

	var failing atomic.Bool
	failing.Store(true)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if failing.Load() {
			w.WriteHeader(http.StatusBadGateway)
			return
		}
		_, _ = w.Write([]byte("vless://uuid@example.com:443#Node"))
	}))
	defer srv.Close()

	owners := []model.ClientRecord{
		{Email: "one@example.com", SubID: "sub-fetch", UUID: "uuid-1", Enable: true},
		{Email: "two@example.com", SubID: "sub-fetch", UUID: "uuid-2", Enable: true},
	}
	for i := range owners {
		if err := db.Create(&owners[i]).Error; err != nil {
			t.Fatalf("seed client %d: %v", i, err)
		}
		row := model.ClientExternalLink{
			ClientId: owners[i].Id,
			Kind:     model.ExternalLinkKindSubscription,
			Value:    srv.URL,
		}
		if err := db.Create(&row).Error; err != nil {
			t.Fatalf("seed external link %d: %v", i, err)
		}
	}

	svc := NewSubService("")
	entries, err := svc.getClientExternalLinksBySubId("sub-fetch")
	if err != nil {
		t.Fatalf("getClientExternalLinksBySubId: %v", err)
	}
	if len(entries) != 2 {
		t.Fatalf("entries = %d, want 2", len(entries))
	}

	for _, e := range entries {
		expandEntry(e)
	}

	var rows []model.ClientExternalLink
	if err := db.Where("value = ?", srv.URL).Find(&rows).Error; err != nil {
		t.Fatalf("read rows: %v", err)
	}
	if len(rows) != 2 {
		t.Fatalf("rows = %d, want 2", len(rows))
	}
	for _, row := range rows {
		if row.LastFetchAt <= 0 {
			t.Fatalf("row %d lastFetchAt = %d, want a stamped timestamp", row.Id, row.LastFetchAt)
		}
		if row.LastFetchError != errBadStatus.Error() {
			t.Fatalf("row %d lastFetchError = %q, want %q", row.Id, row.LastFetchError, errBadStatus)
		}
	}

	failing.Store(false)
	resetSubscriptionCache(t)
	for _, e := range entries {
		expandEntry(e)
	}

	if err := db.Where("value = ?", srv.URL).Find(&rows).Error; err != nil {
		t.Fatalf("re-read rows: %v", err)
	}
	for _, row := range rows {
		if row.LastFetchError != "" {
			t.Fatalf("row %d lastFetchError = %q, want cleared after a good fetch", row.Id, row.LastFetchError)
		}
		if row.LastFetchAt <= 0 {
			t.Fatalf("row %d lastFetchAt = %d, want a stamped timestamp", row.Id, row.LastFetchAt)
		}
	}
}

func TestExpandEntryCacheHitWritesNothing(t *testing.T) {
	initMutDB(t)
	resetSubscriptionCache(t)
	db := database.GetDB()

	const subURL = "https://provider.example/cached"
	rec := model.ClientRecord{Email: "cached@example.com", SubID: "sub-cached", UUID: "uuid", Enable: true}
	if err := db.Create(&rec).Error; err != nil {
		t.Fatalf("seed client: %v", err)
	}
	row := model.ClientExternalLink{ClientId: rec.Id, Kind: model.ExternalLinkKindSubscription, Value: subURL}
	if err := db.Create(&row).Error; err != nil {
		t.Fatalf("seed external link: %v", err)
	}

	subscriptionCache.Lock()
	subscriptionCache.m[subURL] = subscriptionCacheEntry{
		links:     []string{"vless://uuid@example.com:443#Node"},
		fetchedAt: time.Now(),
	}
	subscriptionCache.Unlock()

	if got := expandEntry(externalLinkEntry{Kind: model.ExternalLinkKindSubscription, Value: subURL}); len(got) != 1 {
		t.Fatalf("expandEntry = %#v, want the cached link", got)
	}

	var after model.ClientExternalLink
	if err := db.First(&after, row.Id).Error; err != nil {
		t.Fatalf("read row: %v", err)
	}
	if after.LastFetchAt != 0 || after.LastFetchError != "" {
		t.Fatalf("cache hit wrote fetch status: %#v", after)
	}
}
