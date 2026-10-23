package middleware

import (
	"net/http"
	"testing"

	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
)

func TestRequiredPermissionRoutes(t *testing.T) {
	tests := []struct {
		name   string
		method string
		path   string
		want   string
	}{
		{"inbound list is view", http.MethodGet, "/panel/api/inbounds/list", model.PermInboundsView},
		{"inbound write is manage", http.MethodPost, "/panel/api/inbounds/add", model.PermInboundsManage},
		{"client list is view", http.MethodGet, "/panel/api/clients/list/paged", model.PermClientsView},
		{"client create is manage", http.MethodPost, "/panel/api/clients/add", model.PermClientsManage},
		{"online status is read-only", http.MethodPost, "/panel/api/clients/onlines", model.PermClientsView},
		{"admin api is privileged", http.MethodGet, "/panel/api/admin/list", model.PermAdminsManage},
		{"custom roles api is privileged", http.MethodPost, "/panel/api/roles/add", model.PermAdminsManage},
		{"nodes api needs nodes permission", http.MethodGet, "/panel/api/nodes/list", model.PermNodesManage},
		{"reseller dashboard resolves own data", http.MethodGet, "/panel/api/reseller/overview", ""},
		{"unmapped mutation fails closed", http.MethodPost, "/panel/api/newUnknownAction", "__unmapped_route__"},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := requiredPermission(tc.method, tc.path); got != tc.want {
				t.Fatalf("requiredPermission(%q, %q) = %q, want %q", tc.method, tc.path, got, tc.want)
			}
		})
	}
}

func TestScopedRouteAllowlist(t *testing.T) {
	tests := []struct {
		name   string
		method string
		path   string
		denied bool
	}{
		{"scoped list allowed", http.MethodGet, "/panel/api/clients/list/paged", false},
		{"scoped create allowed", http.MethodPost, "/panel/api/clients/add", false},
		{"scoped attachment allowed for guarded handler", http.MethodPost, "/panel/api/clients/:email/attach", false},
		{"scoped detail allowed for guarded handler", http.MethodGet, "/panel/api/clients/get/:email", false},
		{"global export denied", http.MethodGet, "/panel/api/clients/export", true},
		{"bulk creation denied", http.MethodPost, "/panel/api/clients/bulkCreate", true},
		{"bulk delete denied", http.MethodPost, "/panel/api/clients/bulkDel", true},
		{"global inbound link list denied", http.MethodGet, "/panel/api/inbounds/allLinks", true},
		{"full inbound details denied", http.MethodGet, "/panel/api/inbounds/get/:id", true},
		{"scoped inbound list allowed", http.MethodGet, "/panel/api/inbounds/list", false},
		{"panel settings denied", http.MethodPost, "/panel/api/setting/defaultSettings", true},
		{"reseller's own dashboard allowed", http.MethodGet, "/panel/api/reseller/overview", false},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := scopedRouteDenied(tc.method, tc.path); got != tc.denied {
				t.Fatalf("scopedRouteDenied(%q, %q) = %v, want %v", tc.method, tc.path, got, tc.denied)
			}
		})
	}
}
