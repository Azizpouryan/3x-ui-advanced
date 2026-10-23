package middleware

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
    case strings.HasPrefix(path, "/panel/api/sub-balancers"): return model.PermXrayManage
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
            "/panel/api/clients/:email/attach": {"POST": true},
            "/panel/api/clients/:email/detach": {"POST": true},
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
