# RBAC port report

- Official base: MHSanaei/3x-ui tag v3.8.5.
- Admin source: original main branch of Azizpouryan/3x-ui-advanced.
- Official code is the source of truth; only the RBAC overlay is carried across.

## Files ported

- internal/web/controller/access.go
- internal/web/controller/admin.go
- internal/web/controller/role.go
- internal/web/controller/reseller.go
- internal/web/service/admin.go
- internal/web/service/role.go
- internal/web/service/role_test.go
- frontend/src/lib/permissions.ts
- frontend/src/components/form/OptionButtons.tsx
- frontend/src/components/form/OptionButtons.css
- frontend/src/pages/admins/AdminsPage.tsx
- frontend/src/pages/admins/AdminsPage.css
- frontend/src/pages/admins/RolesCard.tsx
- frontend/src/pages/reseller/ResellerDashboardPage.tsx
- frontend/src/pages/reseller/ResellerDashboardPage.css
- frontend/src/test/permissions.test.ts
- internal/web/session/session.go
- internal/web/controller/base.go

## Port steps

- Original source files: 1037
- Locale JSON files merged: 13
- Frontend integration patches: 2
- Installer/updater files rewritten: 3

This report does not mean tests passed.
