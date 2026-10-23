#!/usr/bin/env python3
"""Rebuild from official v3.8.5, then port the admin/RBAC overlay explicitly."""
from __future__ import annotations
import json, shutil, subprocess, tarfile, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REF = "refs/remotes/origin/main"
TARGET_REF = "refs/tags/port-target-v3.8.5"
REPO = "Azizpouryan/3x-ui-advanced"
RELEASE_TAG = "v3.8.5-advanced.1"
RBAC_FILES = [
    "internal/web/controller/access.go", "internal/web/controller/admin.go",
    "internal/web/controller/role.go", "internal/web/controller/reseller.go",
    "internal/web/service/admin.go", "internal/web/service/role.go",
    "internal/web/service/role_test.go", "frontend/src/lib/permissions.ts",
    "frontend/src/pages/admins/AdminsPage.tsx", "frontend/src/pages/admins/AdminsPage.css",
    "frontend/src/pages/admins/RolesCard.tsx", "frontend/src/pages/reseller/ResellerDashboardPage.tsx",
    "frontend/src/pages/reseller/ResellerDashboardPage.css", "frontend/src/test/permissions.test.ts",
]
KEEP_FILES = ["tools/port-v3.8.5.py", "tools/rebuild-v3.8.5-rbac.py"]
MIDDLEWARE = r'''package middleware

import (
    "net/http"
    "strings"
    "github.com/gin-gonic/gin"
    "github.com/mhsanaei/3x-ui/v3/internal/database/model"
    "github.com/mhsanaei/3x-ui/v3/internal/web/session"
)

// RBACMiddleware is the server-side permission gate.
func RBACMiddleware() gin.HandlerFunc {
    return func(c *gin.Context) {
        fullPath := c.FullPath()
        marker := strings.Index(fullPath, "/panel/api")
        if marker < 0 { c.Next(); return }
        apiPath := fullPath[marker:]
        if strings.HasSuffix(apiPath, "/openapi.json") { c.Next(); return }
        u := session.GetLoginUser(c)
        if u == nil || u.Role == "" || u.Role == model.RoleSuperAdmin { c.Next(); return }
        perm := requiredPermission(c.Request.Method, apiPath)
        if perm != "" && !session.Can(c, perm) {
            c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"success": false, "msg": "forbidden: your admin role cannot perform this action"})
            return
        }
        if session.IsScoped(c) && scopedRouteDenied(c.Request.Method, apiPath) {
            c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"success": false, "msg": "forbidden: this action is not available to scoped admins"})
            return
        }
        c.Next()
    }
}

func requiredPermission(method, path string) string {
    switch {
    case strings.HasPrefix(path, "/panel/api/admin"), strings.HasPrefix(path, "/panel/api/roles"), strings.HasPrefix(path, "/panel/api/shop"):
        return model.PermAdminsManage
    case strings.HasPrefix(path, "/panel/api/setting"):
        return model.PermSettingsManage
    case strings.HasPrefix(path, "/panel/api/xray"):
        return model.PermXrayManage
    case strings.HasPrefix(path, "/panel/api/server"):
        if strings.Contains(strings.ToLower(path), "xray") || strings.Contains(strings.ToLower(path), "geofile") || strings.Contains(strings.ToLower(path), "xrayservice") { return model.PermXrayManage }
        return model.PermSettingsManage
    case strings.HasPrefix(path, "/panel/api/nodes"): return model.PermNodesManage
    case strings.HasPrefix(path, "/panel/api/hosts"): return model.PermHostsManage
    case strings.HasPrefix(path, "/panel/api/plans"): return model.PermPlansManage
    case strings.Contains(path, "/groups"): return model.PermGroupsManage
    case strings.HasPrefix(path, "/panel/api/inbounds"):
        if isReadRoute(method, path) { return model.PermInboundsView }; return model.PermInboundsManage
    case strings.HasPrefix(path, "/panel/api/clients"):
        if isReadRoute(method, path) { return model.PermClientsView }; return model.PermClientsManage
    case strings.HasPrefix(path, "/panel/api/reseller"): return ""
    default:
        return "__unmapped_route__"
    }
}

func isReadRoute(method, path string) bool {
    if method == http.MethodGet || method == http.MethodHead || method == http.MethodOptions { return true }
    for _, ending := range []string{
        "/onlines", "/onlinesByGuid", "/clientIpsByGuid", "/activeInbounds",
        "/lastOnline", "/ips/:email", "/hwids/:email", "/getConfigJson",
        "/getStatus", "/getLogs", "/xraylogs/:count", "/clientIps",
        "/logs/:count", "/getDb", "/getMigration", "/traffic/:email",
        "/subLinks/:subId", "/links/:email", "/happLink/:id",
    } { if strings.HasSuffix(path, ending) { return true } }
    return false
}

func scopedRouteDenied(method, path string) bool {
    for _, prefix := range []string{
        "/panel/api/admin", "/panel/api/roles", "/panel/api/server",
        "/panel/api/setting", "/panel/api/xray", "/panel/api/nodes",
        "/panel/api/hosts", "/panel/api/plans", "/panel/api/shop",
    } { if strings.HasPrefix(path, prefix) { return true } }
    if strings.Contains(path, "/groups") { return true }
    if strings.HasPrefix(path, "/panel/api/inbounds") {
        // Full share-link lists are not safe for a scoped account.
        allowed := map[string]map[string]bool{
            "/panel/api/inbounds/list": {"GET": true},
            "/panel/api/inbounds/list/slim": {"GET": true},
            "/panel/api/inbounds/options": {"GET": true},
        }
        if methods, ok := allowed[path]; !ok || !methods[method] { return true }
    }
    if strings.HasPrefix(path, "/panel/api/clients") {
        // Scoped accounts only see filtered lists and row-level endpoints that
        // receive explicit database-backed scope checks. Everything else denies.
        allowed := map[string]map[string]bool{
            "/panel/api/clients/list": {"GET": true},
            "/panel/api/clients/list/paged": {"GET": true},
            "/panel/api/clients/add": {"POST": true},
            "/panel/api/clients/get/:email": {"GET": true},
            "/panel/api/clients/traffic/:email": {"GET": true},
            "/panel/api/clients/subLinks/:subId": {"GET": true},
            "/panel/api/clients/links/:email": {"GET": true},
            "/panel/api/clients/update/:email": {"POST": true},
            "/panel/api/clients/del/:email": {"POST": true},
            "/panel/api/clients/:email/externalLinks": {"POST": true},
            "/panel/api/clients/resetTraffic/:email": {"POST": true},
            "/panel/api/clients/updateTraffic/:email": {"POST": true},
            "/panel/api/clients/ips/:email": {"POST": true},
            "/panel/api/clients/clearIps/:email": {"POST": true},
            "/panel/api/clients/hwids/:email": {"POST": true, "DELETE": true},
            "/panel/api/clients/hwids/:email/:id": {"DELETE": true},
        }
        if methods, ok := allowed[path]; !ok || !methods[method] { return true }
    }
    return false
}
}
'''

def run(args, stdout=None):
    subprocess.run(args, cwd=ROOT, stdout=stdout, check=True)

def archive(ref, dest):
    tarpath = dest.parent / (dest.name + ".tar")
    with tarpath.open("wb") as handle: run(["git", "archive", ref], stdout=handle)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarpath, "r:") as tf: tf.extractall(dest, filter="data")
    tarpath.unlink(missing_ok=True)

def copy_item(src, rel, destroot):
    if not src.exists() and not src.is_symlink(): return False
    dst = destroot / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        if dst.is_dir() and not dst.is_symlink(): shutil.rmtree(dst)
        else: dst.unlink()
    if src.is_symlink(): dst.symlink_to(src.readlink())
    elif src.is_dir(): shutil.copytree(src, dst, symlinks=True)
    else: shutil.copy2(src, dst)
    return True

def replace_once(text, old, new, label):
    if old not in text: raise RuntimeError("Cannot patch " + label)
    return text.replace(old, new, 1)

def block(text, start, end):
    a = text.find(start); b = text.find(end, a + len(start))
    if a < 0 or b < 0: raise RuntimeError("Cannot extract source block: " + start)
    return text[a:b].rstrip() + "\n\n"

def patch_model(src, dst):
    role = block(src, "// Role constants for the role-based access control (RBAC) layer", "// User represents a user account in the 3x-ui panel.")
    extra = block(src, "// AdminAuditLog records mutations performed by admin users", "// Telegram shop: wallet-funded, pay-as-you-go config sales.")
    methods = block(src, "// PermissionList splits the stored CSV into its permission keys", "// Inbound represents an Xray inbound configuration")
    dst = replace_once(dst, "// User represents a user account in the 3x-ui panel.\n", role + "// User represents a user account in the 3x-ui panel.\n", "role constants")
    ss = src.find("type User struct {"); se = src.find("\n}", ss); user = src[ss:se]
    fs = user.find("\n\t// Role is one of RoleSuperAdmin")
    if fs < 0: raise RuntimeError("RBAC User fields are missing")
    fields = user[fs:]
    ds = dst.find("type User struct {"); de = dst.find("\n}", ds)
    if ds < 0 or de < 0: raise RuntimeError("official User struct is missing")
    dst = dst[:de] + fields + dst[de:]
    dst = replace_once(dst, "// Inbound represents an Xray inbound configuration", extra + methods + "// Inbound represents an Xray inbound configuration", "admin model definitions")
    if '"strconv"' not in dst[:dst.find(")\n\n")]:
        dst = replace_once(dst, '"strings"', '"strconv"\n\t"strings"', "strconv import")
    return dst

def patch_db(dst):
    start = dst.find("func allModels() []any {")
    end = dst.find("\n}", start)
    if start < 0 or end < 0:
        raise RuntimeError("Official database model registry is missing")
    registry = dst[start:end]
    registry = replace_once(
        registry, "\t\t&model.User{},\n",
        "\t\t&model.User{},\n\t\t&model.AdminRole{},\n\t\t&model.AdminAuditLog{},\n\t\t&model.ResellerQuotaDisabledInbound{},\n\t\t&model.Plan{},\n",
        "RBAC AutoMigrate entries",
    )
    return dst[:start] + registry + dst[end:]

def patch_api(dst):
    marker = '\tapi.GET("/openapi.json", ServeOpenAPISpec)\n'
    addition = marker + '''
    // Multi-admin RBAC endpoints.
    admins := api.Group("/admin")
    admins.Use(requireSuperAdmin())
    NewAdminController(admins)

    roles := api.Group("/roles")
    roles.Use(requirePermission(model.PermAdminsManage))
    NewRoleController(roles)

    reseller := api.Group("/reseller")
    NewResellerController(reseller)
'''
    dst = replace_once(dst, marker, addition, "admin endpoints")
    return replace_once(dst, "\tapi.Use(a.checkAPIAuth)\n",
        "\tapi.Use(a.checkAPIAuth)\n\tapi.Use(middleware.RBACMiddleware())\n", "global RBAC middleware")

def patch_web(dst):
    if '"github.com/mhsanaei/3x-ui/v3/internal/web/session"' not in dst:
        dst = replace_once(dst, '"github.com/mhsanaei/3x-ui/v3/internal/web/service"\n',
            '"github.com/mhsanaei/3x-ui/v3/internal/web/service"\n\t"github.com/mhsanaei/3x-ui/v3/internal/web/session"\n', "session import")
    return replace_once(dst, "func (s *Server) initRouter() (*gin.Engine, error) {\n",
        "func (s *Server) initRouter() (*gin.Engine, error) {\n\tsession.SetPermissionResolver(service.PermissionsForRole)\n\tservice.ReloadRoleCache()\n", "permission resolver initialization")

def patch_session(src, dst):
    # Keep the v3.8.5 auth/session implementation intact and transplant only
    # the RBAC helpers added by the fork.
    if '"strings"' not in dst[:dst.find(")\n\n")]:
        dst = replace_once(dst, '\t"time"\n', '\t"strings"\n\t"time"\n', "session strings import")
    block_text = block(src, "// HasRole reports whether the currently logged-in user", "func sessionUserID(obj any) (int, bool) {")
    return replace_once(dst, "func sessionUserID(obj any) (int, bool) {", block_text + "func sessionUserID(obj any) (int, bool) {", "session RBAC helpers")


def patch_base(src, dst):
    # Preserve upstream login behaviour; insert only permission middleware helpers.
    if '"strings"' not in dst[:dst.find(")\n\n")]:
        dst = replace_once(dst, '\t"net/http"\n', '\t"net/http"\n\t"strings"\n', "base strings import")
    if '"github.com/mhsanaei/3x-ui/v3/internal/database/model"' not in dst:
        dst = replace_once(
            dst,
            '\t"github.com/mhsanaei/3x-ui/v3/internal/logger"\n',
            '\t"github.com/mhsanaei/3x-ui/v3/internal/database/model"\n\t"github.com/mhsanaei/3x-ui/v3/internal/logger"\n',
            "base RBAC model import",
        )
    block_text = block(src, "// requireRole returns a Gin middleware", "// I18nWeb retrieves an internationalized message")
    return replace_once(dst, "// I18nWeb retrieves an internationalized message", block_text + "// I18nWeb retrieves an internationalized message", "base RBAC helpers")


def patch_access(dst):
    # Use v3.8.5's database models for scope checks instead of methods that only
    # exist in the older fork. Every record and every attachment must be in scope.
    dst = replace_once(
        dst,
        '\t"github.com/mhsanaei/3x-ui/v3/internal/database/model"\n',
        '\t"github.com/mhsanaei/3x-ui/v3/internal/database"\n\t"github.com/mhsanaei/3x-ui/v3/internal/database/model"\n',
        "database import for scope checks",
    )

    f_start = dst.find("func filterClientsForRole(")
    f_end = dst.find("// guardClientEmailScope", f_start)
    if f_start < 0 or f_end < 0:
        raise RuntimeError("Cannot locate client list scope helpers")
    filter_func = """func filterClientsForRole(c *gin.Context, rows []service.ClientWithAttachments) []service.ClientWithAttachments {
\tset, scoped := resellerAllowedSet(c)
\tif !scoped {
\t\treturn rows
\t}
\tout := make([]service.ClientWithAttachments, 0, len(rows))
\tfor _, row := range rows {
\t\tif len(row.InboundIds) == 0 {
\t\t\tcontinue
\t\t}
\t\tallAllowed := true
\t\tfor _, inboundID := range row.InboundIds {
\t\t\tif _, ok := set[inboundID]; !ok {
\t\t\t\tallAllowed = false
\t\t\t\tbreak
\t\t\t}
\t\t}
\t\tif allAllowed {
\t\t\tout = append(out, row)
\t\t}
\t}
\treturn out
}

// scopeAllowsClientRecords requires at least one inbound association per client
// and rejects the entire record if any attachment is outside the allowed set.
func scopeAllowsClientRecords(set map[int]struct{}, records []model.ClientRecord) bool {
\tif len(records) == 0 {
\t\treturn false
\t}
\tfor _, record := range records {
\t\tvar ids []int
\t\tif err := database.GetDB().Model(&model.ClientInbound{}).
\t\t\tWhere("client_id = ?", record.Id).Pluck("inbound_id", &ids).Error; err != nil || len(ids) == 0 {
\t\t\treturn false
\t\t}
\t\tfor _, id := range ids {
\t\t\tif _, ok := set[id]; !ok {
\t\t\t\treturn false
\t\t\t}
\t\t}
\t}
\treturn true
}

"""
    dst = dst[:f_start] + filter_func + dst[f_end:]

    e_start = dst.find("func guardClientEmailScope(")
    e_end = dst.find("// guardInboundIdsScope", e_start)
    if e_start < 0 or e_end < 0:
        raise RuntimeError("Cannot locate client detail scope guards")
    guards = """func guardClientEmailScope(c *gin.Context, _ *service.ClientService, email string) bool {
\tset, scoped := resellerAllowedSet(c)
\tif !scoped {
\t\treturn true
\t}
\tvar records []model.ClientRecord
\tif err := database.GetDB().Where("email = ?", email).Find(&records).Error; err == nil &&
\t\tscopeAllowsClientRecords(set, records) {
\t\treturn true
\t}
\tpureJsonMsg(c, http.StatusForbidden, false, "forbidden: client is outside your reseller scope")
\tc.Abort()
\treturn false
}

// guardClientSubIdScope validates every client record sharing a subscription id.
func guardClientSubIdScope(c *gin.Context, _ *service.ClientService, subId string) bool {
\tset, scoped := resellerAllowedSet(c)
\tif !scoped {
\t\treturn true
\t}
\tvar records []model.ClientRecord
\tif err := database.GetDB().Where("sub_id = ?", subId).Find(&records).Error; err == nil &&
\t\tscopeAllowsClientRecords(set, records) {
\t\treturn true
\t}
\tpureJsonMsg(c, http.StatusForbidden, false, "forbidden: subscription is outside your reseller scope")
\tc.Abort()
\treturn false
}

// 
"""
    return dst[:e_start] + guards + dst[e_end:]




def patch_dist(dst):
    dst = replace_once(
        dst,
        '\t"github.com/mhsanaei/3x-ui/v3/internal/config"\n',
        '\t"github.com/mhsanaei/3x-ui/v3/internal/config"\n\t"github.com/mhsanaei/3x-ui/v3/internal/database/model"\n',
        "RBAC model import in SPA bootstrap",
    )
    dst = replace_once(
        dst,
        '\t"github.com/mhsanaei/3x-ui/v3/internal/web/session"\n',
        '\t"github.com/mhsanaei/3x-ui/v3/internal/web/session"\n\t"github.com/mhsanaei/3x-ui/v3/internal/web/service"\n',
        "RBAC service import in SPA bootstrap",
    )
    marker = "\t\tscript += §;window.X_UI_DB_TYPE=\"§ + config.GetDBKind() + §\"§\n"
    marker = marker.replace("§", chr(96))
    addition = marker + """
\t\trole := model.RoleSuperAdmin
\t\tif u := session.GetLoginUser(c); u != nil && u.Role != "" {
\t\t\trole = u.Role
\t\t}
\t\tscript += §;window.X_UI_ROLE="§ + jsEscape.Replace(role) + §"§
\t\tscript += §;window.X_UI_ROLE_NAME="§ + jsEscape.Replace(service.RoleDisplayName(role)) + §"§
\t\tperms := session.PermissionsOf(&model.User{Role: role})
\t\tgranted := make([]string, 0, len(model.AllPermissions))
\t\tfor _, p := range model.AllPermissions {
\t\t\tif perms[p] {
\t\t\t\tgranted = append(granted, §"§+jsEscape.Replace(p)+§"§)
\t\t\t}
\t\t}
\t\tscript += §;window.X_UI_PERMS=[§ + strings.Join(granted, ",") + §]§
""".replace("§", chr(96))
    return replace_once(dst, marker, addition, "inject role and permission globals")


def patch_env(dst):
    return replace_once(
        dst,
        "  X_UI_DB_TYPE?: string;\n",
        "  X_UI_DB_TYPE?: string;\n"
        "  X_UI_ROLE?: string;\n"
        "  X_UI_ROLE_NAME?: string;\n"
        "  X_UI_PERMS?: string[];\n",
        "frontend RBAC window types",
    )


def patch_client_paging(dst):
    tick = chr(96)
    params_marker = '\tGroup      string ' + tick + 'form:"group"' + tick + '\n'
    params_fields = params_marker + '\tScopeEnabled bool ' + tick + 'form:"-" json:"-"' + tick + '\n'
    params_fields += '\tScopeInboundIDs []int ' + tick + 'form:"-" json:"-"' + tick + '\n'
    dst = replace_once(dst, params_marker, params_fields, "internal client paging scope params")

    query_marker = '\tnowMs            int64\n'
    dst = replace_once(
        dst, query_marker,
        query_marker + '\tscopeEnabled     bool\n\tscopeInboundIDs  []int\n',
        "client query scope fields",
    )

    from_start = dst.find("func (q clientQuery) from() *gorm.DB {")
    from_end = dst.find("\n}", from_start)
    if from_start < 0 or from_end < 0:
        raise RuntimeError("Cannot locate client query FROM builder")
    from_func = """func (q clientQuery) from() *gorm.DB {
\ttx := q.db.Table("clients AS c")
\tfor _, j := range q.joins {
\t\ttx = tx.Joins(j.sql, j.args...)
\t}
\tif q.scopeEnabled {
\t\tif len(q.scopeInboundIDs) == 0 {
\t\t\treturn tx.Where("1 = 0")
\t\t}
\t\ttx = tx.Where(
\t\t\t"EXISTS (SELECT 1 FROM client_inbounds scope_ci WHERE scope_ci.client_id = c.id AND scope_ci.inbound_id IN ?)",
\t\t\tq.scopeInboundIDs,
\t\t).Where(
\t\t\t"NOT EXISTS (SELECT 1 FROM client_inbounds scope_ci WHERE scope_ci.client_id = c.id AND scope_ci.inbound_id NOT IN ?)",
\t\t\tq.scopeInboundIDs,
\t\t)
\t}
\treturn tx
}"""
    dst = dst[:from_start] + from_func + dst[from_end + 2:]

    marker = '\tq := newClientQuery(db, time.Now().UnixMilli(), expireDiffMs, trafficDiffBytes)\n'
    dst = replace_once(
        dst, marker,
        marker + '\tq.scopeEnabled = params.ScopeEnabled\n\tq.scopeInboundIDs = params.ScopeInboundIDs\n',
        "scoped client query setup",
    )

    total_old = """\tvar total int64
\tif err := db.Model(&model.ClientRecord{}).Count(&total).Error; err != nil {
\t\treturn nil, err
\t}"""
    total_new = """\tvar total int64
\tif params.ScopeEnabled {
\t\tif len(params.ScopeInboundIDs) == 0 {
\t\t\ttotal = 0
\t\t} else if err := q.from().Distinct("c.id").Count(&total).Error; err != nil {
\t\t\treturn nil, err
\t\t}
\t} else if err := db.Model(&model.ClientRecord{}).Count(&total).Error; err != nil {
\t\treturn nil, err
\t}"""
    dst = replace_once(dst, total_old, total_new, "scope-safe total count")

    group_old = """\tgroups, err := s.listGroupNames()
\tif err != nil {
\t\treturn nil, err
\t}"""
    group_new = """\tvar groups []string
\tif !params.ScopeEnabled {
\t\tgroups, err = s.listGroupNames()
\t\tif err != nil {
\t\t\treturn nil, err
\t\t}
\t} else {
\t\tgroups = []string{}
\t}"""
    dst = replace_once(dst, group_old, group_new, "hide global group names from scoped accounts")

    online_start = dst.find("func (q clientQuery) onlineEmails(")
    online_end = dst.find("\n}", online_start)
    if online_start < 0 or online_end < 0:
        raise RuntimeError("Cannot locate online email query")
    online_func = """func (q clientQuery) onlineEmails(onlines []string) ([]string, int, error) {
\tmatched := []string{}
\tcount := 0
\tfor _, batch := range chunkStrings(onlines, sqlInChunk) {
\t\tvar page []string
\t\tvar query *gorm.DB
\t\tcolumn := "email"
\t\tif q.scopeEnabled {
\t\t\tquery = q.from().
\t\t\t\tWhere("COALESCE(c.enable, FALSE) = TRUE AND c.email IN ?", batch).
\t\t\t\tOrder("c.id ASC")
\t\t\tcolumn = "c.email"
\t\t} else {
\t\t\tquery = q.db.Model(&model.ClientRecord{}).
\t\t\t\tWhere("COALESCE(enable, FALSE) = TRUE AND email IN ?", batch).
\t\t\t\tOrder("id ASC")
\t\t}
\t\tif err := query.Pluck(column, &page).Error; err != nil {
\t\t\treturn nil, 0, err
\t\t}
\t\tcount += len(page)
\t\tif room := clientSummaryEmailCap - len(matched); room > 0 {
\t\t\tmatched = append(matched, page[:min(room, len(page))]...)
\t\t}
\t}
\treturn matched, count, nil
}"""
    dst = dst[:online_start] + online_func + dst[online_end + 2:]
    return dst


def patch_inbounds(dst):
    dst = replace_once(
        dst,
        "\tinbounds, err := a.inboundService.GetInbounds(user.Id)",
        "\tvar inbounds []*model.Inbound\n\tvar err error\n\tif session.IsScoped(c) {\n\t\tinbounds, err = a.inboundService.GetInboundsSlim(user.Id)\n\t} else {\n\t\tinbounds, err = a.inboundService.GetInbounds(user.Id)\n\t}",
        "scoped inbound list redaction",
    )
    dst = replace_once(dst, 'g.GET("/get/:id", a.getInbound)', 'g.GET("/get/:id", scopeInboundParam, a.getInbound)', "inbound detail scope")
    dst = replace_once(dst, 'g.GET("/:id/fallbacks", a.getFallbacks)', 'g.GET("/:id/fallbacks", scopeInboundParam, a.getFallbacks)', "fallback read scope")
    dst = replace_once(dst, 'g.POST("/:id/fallbacks", a.setFallbacks)', 'g.POST("/:id/fallbacks", scopeInboundParam, a.setFallbacks)', "fallback write scope")
    dst = replace_once(dst, "jsonObj(c, inbounds, nil)", "jsonObj(c, filterInboundsForRole(c, inbounds), nil)", "inbound list filter")
    dst = replace_once(dst, "jsonObj(c, inbounds, nil)", "jsonObj(c, filterInboundsForRole(c, inbounds), nil)", "slim inbound list filter")
    return replace_once(dst, "jsonObj(c, options, nil)", "jsonObj(c, filterInboundOptionsForRole(c, options), nil)", "inbound option filter")

def patch_clients(source, dst):
    if '"github.com/mhsanaei/3x-ui/v3/internal/web/session"' not in dst:
        dst = replace_once(
            dst,
            '"github.com/mhsanaei/3x-ui/v3/internal/web/service"\n',
            '"github.com/mhsanaei/3x-ui/v3/internal/web/service"\n\t"github.com/mhsanaei/3x-ui/v3/internal/web/session"\n',
            "client session import",
        )

    dst = replace_once(
        dst,
        "\tsettingService service.SettingService\n\thappGenerator  service.HappLinkGenerator",
        "\tsettingService service.SettingService\n\tadminService   service.AdminService\n\thappGenerator  service.HappLinkGenerator",
        "client controller admin service field",
    )

    quota_helpers = block(source, "const bytesPerGB =", "func parseInboundIdsQuery(raw string) []int {")
    quota_helpers = replace_once(
        quota_helpers,
        "\tif err != nil {\n\t\treturn true\n\t}",
        "\tif err != nil {\n\t\tjsonMsg(c, I18nWeb(c, \"somethingWentWrong\"), err)\n\t\tc.Abort()\n\t\treturn false\n\t}",
        "fail-closed reseller quota lookup",
    )
    dst = replace_once(
        dst,
        "func parseInboundIdsQuery(raw string) []int {",
        quota_helpers + "func parseInboundIdsQuery(raw string) []int {",
        "reseller quota enforcement helpers",
    )

    marker = "func (a *ClientController) initRouter(g *gin.RouterGroup) {\n"
    closures = marker + """\tscopeEmail := func(c *gin.Context) {
\t\tif guardClientEmailScope(c, &a.clientService, c.Param("email")) { c.Next() }
\t}
\tscopeSubID := func(c *gin.Context) {
\t\tif guardClientSubIdScope(c, &a.clientService, c.Param("subId")) { c.Next() }
\t}
"""
    dst = replace_once(dst, marker, closures, "client scope closures")
    pairs = [
        ('g.GET("/get/:email", a.get)', 'g.GET("/get/:email", scopeEmail, a.get)'),
        ('g.GET("/traffic/:email", a.getTrafficByEmail)', 'g.GET("/traffic/:email", scopeEmail, a.getTrafficByEmail)'),
        ('g.GET("/subLinks/:subId", a.getSubLinks)', 'g.GET("/subLinks/:subId", scopeSubID, a.getSubLinks)'),
        ('g.GET("/links/:email", a.getClientLinks)', 'g.GET("/links/:email", scopeEmail, a.getClientLinks)'),
        ('g.POST("/update/:email", a.update)', 'g.POST("/update/:email", scopeEmail, a.update)'),
        ('g.POST("/del/:email", a.delete)', 'g.POST("/del/:email", scopeEmail, a.delete)'),
        ('g.POST("/:email/attach", a.attach)', 'g.POST("/:email/attach", scopeEmail, a.attach)'),
        ('g.POST("/:email/detach", a.detach)', 'g.POST("/:email/detach", scopeEmail, a.detach)'),
        ('g.POST("/:email/externalLinks", a.setExternalLinks)', 'g.POST("/:email/externalLinks", scopeEmail, a.setExternalLinks)'),
        ('g.POST("/resetTraffic/:email", a.resetTrafficByEmail)', 'g.POST("/resetTraffic/:email", scopeEmail, a.resetTrafficByEmail)'),
        ('g.POST("/updateTraffic/:email", a.updateTrafficByEmail)', 'g.POST("/updateTraffic/:email", scopeEmail, a.updateTrafficByEmail)'),
        ('g.POST("/ips/:email", a.getIps)', 'g.POST("/ips/:email", scopeEmail, a.getIps)'),
        ('g.POST("/clearIps/:email", a.clearIps)', 'g.POST("/clearIps/:email", scopeEmail, a.clearIps)'),
        ('g.POST("/hwids/:email", a.getHwids)', 'g.POST("/hwids/:email", scopeEmail, a.getHwids)'),
        ('g.DELETE("/hwids/:email", a.clearHwids)', 'g.DELETE("/hwids/:email", scopeEmail, a.clearHwids)'),
        ('g.DELETE("/hwids/:email/:id", a.deleteHwid)', 'g.DELETE("/hwids/:email/:id", scopeEmail, a.deleteHwid)'),
    ]
    for old, new in pairs:
        dst = replace_once(dst, old, new, old)

    listpaged = """\tif session.IsScoped(c) {
\t\tparams.ScopeEnabled = true
\t\tparams.ScopeInboundIDs = service.AllowedInboundIDs(session.GetLoginUser(c))
\t}
\tresp, err := a.clientService.ListPaged(&a.inboundService, &a.settingService, params)"""
    dst = replace_once(
        dst,
        "\tresp, err := a.clientService.ListPaged(&a.inboundService, &a.settingService, params)",
        listpaged,
        "scope-aware paginated client listing",
    )

    dst = replace_once(
        dst,
        "\tneedRestart, err := a.clientService.Create(&a.inboundService, &payload)",
        "\tif !guardInboundIdsScope(c, payload.InboundIds) {\n\t\treturn\n\t}\n\tif !a.enforceResellerQuota(c) {\n\t\treturn\n\t}\n\tneedRestart, err := a.clientService.Create(&a.inboundService, &payload)",
        "client create scope and quota checks",
    )
    dst = replace_once(
        dst,
        "\tjsonMsgObj(c, I18nWeb(c, \"pages.inbounds.toasts.inboundClientAddSuccess\"), pendingNodeObj(a.inboundService.AnyNodePending(payload.InboundIds)), nil)",
        "\ta.incrementResellerCreated(c, 1)\n\tjsonMsgObj(c, I18nWeb(c, \"pages.inbounds.toasts.inboundClientAddSuccess\"), pendingNodeObj(a.inboundService.AnyNodePending(payload.InboundIds)), nil)",
        "reseller created-client counter",
    )
    return replace_once(dst, "jsonObj(c, rows, nil)", "jsonObj(c, filterClientsForRole(c, rows), nil)", "client list filter")



def rewrite_installer(root):
    count = 0
    for rel in ("install.sh", "update.sh", "x-ui.sh"):
        p = root / rel
        if not p.is_file():
            continue
        old = p.read_text(encoding="utf-8")
        new = old.replace("MHSanaei/3x-ui", REPO).replace("mhsanaei/3x-ui", REPO).replace("admin6501/3x-ui", REPO)
        new = new.replace(
            "raw.githubusercontent.com/" + REPO + "/main/",
            "raw.githubusercontent.com/" + REPO + "/rebuild/v3.8.5-rbac/",
        )

        if rel == "install.sh":
            marker = "install_x-ui() {"
            if marker in new and RELEASE_TAG not in new:
                gate = marker + '''
    requested_release="${1:-}"
    if [[ -z "$requested_release" ]]; then
        requested_release="$(curl -fsSL --retry 3 "https://api.github.com/repos/''' + REPO + '''/releases/latest" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\\1/')"
    fi
    if [[ "$requested_release" != "''' + RELEASE_TAG + '''" ]]; then
        echo "RBAC v3.8.5 build is not validated. Refusing to install ${requested_release:-unknown}." >&2
        exit 1
    fi
'''
                new = new.replace(marker, gate, 1)

        if rel == "update.sh":
            marker = "update_x-ui() {"
            if marker in new and RELEASE_TAG not in new:
                gate = marker + '''
    requested_release="${XUI_UPDATE_TAG:-${1:-}}"
    if [[ -z "$requested_release" ]]; then
        requested_release="$(curl -fsSL --retry 3 "https://api.github.com/repos/''' + REPO + '''/releases/latest" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\\1/')"
    fi
    if [[ "$requested_release" != "''' + RELEASE_TAG + '''" ]]; then
        echo "RBAC v3.8.5 build is not validated. Refusing to update to ${requested_release:-unknown}." >&2
        exit 1
    fi
    export XUI_UPDATE_TAG="$requested_release"
'''
                new = new.replace(marker, gate, 1)

        if new != old:
            p.write_text(new, encoding="utf-8", newline="")
            count += 1
    return count


def merge_locales(srcroot, outroot):
    srcbase = srcroot / "internal/web/translation"; dstbase = outroot / "internal/web/translation"
    if not srcbase.exists() or not dstbase.exists(): return 0
    count = 0
    def merge(base, extra):
        if isinstance(base, dict) and isinstance(extra, dict):
            for k, v in extra.items():
                if k not in base: base[k] = v
                elif isinstance(base[k], dict) and isinstance(v, dict): merge(base[k], v)
        return base
    for src in srcbase.rglob("*.json"):
        dst = outroot / src.relative_to(srcroot)
        try:
            extra = json.loads(src.read_text(encoding="utf-8"))
            if not dst.exists():
                copy_item(src, src.relative_to(srcroot).as_posix(), outroot); count += 1; continue
            old = dst.read_text(encoding="utf-8")
            rendered = json.dumps(merge(json.loads(old), extra), ensure_ascii=False, indent=2) + "\n"
            if rendered != old: dst.write_text(rendered, encoding="utf-8", newline=""); count += 1
        except (ValueError, UnicodeDecodeError): pass
    return count

def patch_frontend(root):
    count = 0
    rp = root / "frontend/src/routes.tsx"
    routes = rp.read_text(encoding="utf-8")
    if "const AdminsPage =" not in routes:
        routes = routes.replace("import { createBrowserRouter, type RouteObject } from 'react-router';",
            "import { createBrowserRouter, Navigate, type RouteObject } from 'react-router';")
        routes = replace_once(routes, "const ApiDocsPage = lazy(() => import('@/pages/api-docs/ApiDocsPage'));\n",
            "const ApiDocsPage = lazy(() => import('@/pages/api-docs/ApiDocsPage'));\n"
            "const AdminsPage = lazy(() => import('@/pages/admins/AdminsPage'));\n"
            "const ResellerDashboardPage = lazy(() => import('@/pages/reseller/ResellerDashboardPage'));\n", "admin frontend imports")
        routes = replace_once(routes, "const routes: RouteObject[] = [",
            '''function IndexRoute() {
  const role = (typeof window !== 'undefined' && window.X_UI_ROLE) || 'super_admin';
  const permissions = new Set(
    typeof window !== 'undefined' && Array.isArray(window.X_UI_PERMS) ? window.X_UI_PERMS : [],
  );
  if (permissions.has('inbounds.scoped')) return <Navigate to="/usage" replace />;
  // The system dashboard calls server-wide status, update, and settings APIs.
  // Roles that do not have those permissions should land on an allowed page
  // instead of rendering a dashboard full of expected 403 responses.
  if (role !== 'super_admin' && !permissions.has('settings.manage') && !permissions.has('xray.manage')) {
    return <Navigate to={permissions.has('inbounds.view') ? '/inbounds' : '/clients'} replace />;
  }
  return withSuspense(<IndexPage />);
}

function AdminsRoute() {
  const role = (typeof window !== 'undefined' && window.X_UI_ROLE) || 'super_admin';
  if (role !== 'super_admin') return <Navigate to="/" replace />;
  return withSuspense(<AdminsPage />);
}

function ResellerRoute() {
  const scoped = typeof window !== 'undefined' && Array.isArray(window.X_UI_PERMS) && window.X_UI_PERMS.includes('inbounds.scoped');
  if (!scoped) return <Navigate to="/" replace />;
  return withSuspense(<ResellerDashboardPage />);
}

const routes: RouteObject[] = ['', "admin UI guard")
        routes = replace_once(routes, "{ index: true, element: withSuspense(<IndexPage />) },",
            "{ index: true, element: <IndexRoute /> },", "scoped dashboard redirect")
        routes = replace_once(routes, "{ path: 'api-docs', element: withSuspense(<ApiDocsPage />) },",
            "{ path: 'api-docs', element: withSuspense(<ApiDocsPage />) },\n"
            "      { path: 'admins', element: <AdminsRoute /> },\n"
            "      { path: 'usage', element: <ResellerRoute /> },", "admin routes")
        rp.write_text(routes, encoding="utf-8", newline=""); count += 1
    sp = root / "frontend/src/layouts/AppSidebar.tsx"
    sidebar = sp.read_text(encoding="utf-8")
    if "| 'admins'" not in sidebar:
        sidebar = replace_once(sidebar, "  | 'routing';", "  | 'routing'\n  | 'admins'\n  | 'usage';", "sidebar icon type")
        sidebar = replace_once(sidebar, "  routing: SwapOutlined,\n};",
            "  routing: SwapOutlined,\n  admins: SafetyOutlined,\n  usage: TeamOutlined,\n};", "sidebar icon map")
        sidebar = replace_once(sidebar, "      { key: '/api-docs', icon: 'apidocs', title: t('menu.apiDocs') },",
            "      { key: '/api-docs', icon: 'apidocs', title: t('menu.apiDocs') },\n"
            "      { key: '/admins', icon: 'admins', title: t('menu.admins') },\n"
            "      { key: '/usage', icon: 'usage', title: t('menu.usage') },", "sidebar items")
        sidebar = replace_once(
            sidebar,
            "  const navItems = useMemo(() => tabs.filter((tab) => tab.icon !== 'logout'), [tabs]);",
            """  const role = (typeof window !== 'undefined' && window.X_UI_ROLE) || 'super_admin';
  const permissionKey = typeof window !== 'undefined' && Array.isArray(window.X_UI_PERMS)
    ? window.X_UI_PERMS.join(',')
    : '';
  const permissions = new Set(permissionKey.split(',').filter(Boolean));
  const scoped = permissions.has('inbounds.scoped');
  const navItems = useMemo(
    () => tabs.filter((tab) => {
      if (tab.icon === 'logout') return false;
      if (tab.key === '/admins') return role === 'super_admin';
      if (tab.key === '/usage') return scoped;
      if (scoped && tab.key === '/groups') return false;
      const required: Record<string, string> = {
        '/inbounds': 'inbounds.view',
        '/clients': 'clients.view',
        '/groups': 'groups.manage',
        '/nodes': 'nodes.manage',
        '/hosts': 'hosts.manage',
        '/settings': 'settings.manage',
        '/xray': 'xray.manage',
        '/outbound': 'xray.manage',
        '/routing': 'xray.manage',
      };
      const perm = required[tab.key];
      return !perm || permissions.has(perm);
    }),
    [tabs, role, scoped, permissionKey],
  );""",
            "role-aware sidebar entries",
        )
        sp.write_text(sidebar, encoding="utf-8", newline=""); count += 1
    return count

def count_files(root):
    return sum(1 for p in root.rglob("*") if p.is_file() or p.is_symlink())

def main():
    for ref in (SOURCE_REF, TARGET_REF): run(["git", "rev-parse", "--verify", ref])
    temp = Path(tempfile.mkdtemp(prefix="v385-rbac-"))
    try:
        source, target, current, output = (temp / n for n in ("source", "target", "current", "output"))
        archive(SOURCE_REF, source); archive(TARGET_REF, target); archive("HEAD", current)
        shutil.copytree(target, output, symlinks=True)
        copy_item(current / ".github", ".github", output)
        for rel in KEEP_FILES: copy_item(current / rel, rel, output)
        copied = []
        for rel in RBAC_FILES:
            if copy_item(source / rel, rel, output): copied.append(rel)

        sessp = output / "internal/web/session/session.go"
        sessp.write_text(patch_session((source / "internal/web/session/session.go").read_text(encoding="utf-8"),
                                       sessp.read_text(encoding="utf-8")), encoding="utf-8", newline="")
        copied.append("internal/web/session/session.go")
        basep = output / "internal/web/controller/base.go"
        basep.write_text(patch_base((source / "internal/web/controller/base.go").read_text(encoding="utf-8"),
                                    basep.read_text(encoding="utf-8")), encoding="utf-8", newline="")
        copied.append("internal/web/controller/base.go")

        mp = output / "internal/database/model/model.go"
        mp.write_text(patch_model((source / "internal/database/model/model.go").read_text(encoding="utf-8"),
                                  mp.read_text(encoding="utf-8")), encoding="utf-8", newline="")
        dp = output / "internal/database/db.go"
        dp.write_text(patch_db(dp.read_text(encoding="utf-8")), encoding="utf-8", newline="")
        ap = output / "internal/web/controller/api.go"
        ap.write_text(patch_api(ap.read_text(encoding="utf-8")), encoding="utf-8", newline="")
        wp = output / "internal/web/web.go"
        wp.write_text(patch_web(wp.read_text(encoding="utf-8")), encoding="utf-8", newline="")
        distp = output / "internal/web/controller/dist.go"
        distp.write_text(patch_dist(distp.read_text(encoding="utf-8")), encoding="utf-8", newline="")
        envp = output / "frontend/src/env.d.ts"
        envp.write_text(patch_env(envp.read_text(encoding="utf-8")), encoding="utf-8", newline="")
        accessp = output / "internal/web/controller/access.go"
        accessp.write_text(patch_access(accessp.read_text(encoding="utf-8")), encoding="utf-8", newline="")
        ip = output / "internal/web/controller/inbound.go"
        ip.write_text(patch_inbounds(ip.read_text(encoding="utf-8")), encoding="utf-8", newline="")
        cp = output / "internal/web/controller/client.go"
        cp.write_text(patch_clients((source / "internal/web/controller/client.go").read_text(encoding="utf-8"), cp.read_text(encoding="utf-8")), encoding="utf-8", newline="")
        pagingp = output / "internal/web/service/client_paging.go"
        pagingp.write_text(patch_client_paging(pagingp.read_text(encoding="utf-8")), encoding="utf-8", newline="")
        rb = output / "internal/web/middleware/rbac.go"
        rb.parent.mkdir(parents=True, exist_ok=True); rb.write_text(MIDDLEWARE, encoding="utf-8", newline="")
        locale_count = merge_locales(source, output)
        frontend_count = patch_frontend(output)
        url_count = rewrite_installer(output)

        readme = output / "README.md"
        if readme.exists():
            text = readme.read_text(encoding="utf-8").replace("# 3X-UI", "# 3X-UI Advanced — official v3.8.5 with multi-admin RBAC", 1)
            text += "\n\n## Multi-admin RBAC overlay\n\nThis repository starts from official MHSanaei/3x-ui v3.8.5 and ports multi-admin role management, scoped reseller access, custom roles, and the Admins page. Release is gated on passing CI.\n"
            readme.write_text(text, encoding="utf-8", newline="")
        status = "# v3.8.5 RBAC rebuild status\n\nRebuilt from official MHSanaei/3x-ui tag v3.8.5. This is an unvalidated candidate. CI must pass frontend build, shell checks, Go tests, and Linux binary build before release. Do not install on a production server until release v3.8.5-advanced.1 exists.\n"
        (output / "MIGRATION_STATUS_v3.8.5.md").write_text(status, encoding="utf-8", newline="")
        details = ["# RBAC port report", "", "- Official base: MHSanaei/3x-ui tag v3.8.5.", "- Admin source: original main branch of Azizpouryan/3x-ui-advanced.", "- Official code is the source of truth; only the RBAC overlay is carried across.", "", "## Files ported", ""] + ["- " + p for p in copied] + ["", "## Port steps", "", "- Original source files: " + str(count_files(source)), "- Locale JSON files merged: " + str(locale_count), "- Frontend integration patches: " + str(frontend_count), "- Installer/updater files rewritten: " + str(url_count), "", "This report does not mean tests passed.", ""]
        (output / "PORTING_REPORT_v3.8.5.md").write_text("\n".join(details), encoding="utf-8", newline="")

        for child in ROOT.iterdir():
            if child.name == ".git": continue
            if child.is_symlink() or child.is_file(): child.unlink()
            elif child.is_dir(): shutil.rmtree(child)
        for child in output.iterdir():
            dst = ROOT / child.name
            if child.is_symlink(): dst.symlink_to(child.readlink())
            elif child.is_dir(): shutil.copytree(child, dst, symlinks=True)
            else: shutil.copy2(child, dst)
        print("Rebuilt official v3.8.5 tree; RBAC files ported: " + str(len(copied)))
        print("Locales merged: " + str(locale_count) + "; frontend patches: " + str(frontend_count))
    finally:
        shutil.rmtree(temp, ignore_errors=True)

if __name__ == "__main__":
    main()
