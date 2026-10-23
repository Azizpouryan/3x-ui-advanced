package panel

import (
	"path/filepath"
	"testing"

	"github.com/mhsanaei/3x-ui/v3/internal/database"
	"github.com/mhsanaei/3x-ui/v3/internal/database/model"
)

func TestCheckUserRejectsDisabledAccount(t *testing.T) {
	dbDir := t.TempDir()
	t.Setenv("XUI_DB_FOLDER", dbDir)
	if err := database.InitDB(filepath.Join(dbDir, "x-ui.db")); err != nil {
		t.Fatalf("InitDB: %v", err)
	}
	t.Cleanup(func() { _ = database.CloseDB() })

	user := &model.User{
		Username: "disabled-admin-test",
		Password: "hash-is-not-consulted-for-disabled-account",
		Disabled: true,
	}
	if err := database.GetDB().Create(user).Error; err != nil {
		t.Fatalf("create disabled user: %v", err)
	}

	got, err := (&UserService{}).CheckUser(user.Username, "any-password", "")
	if err == nil {
		t.Fatal("CheckUser succeeded for a disabled account")
	}
	if got != nil {
		t.Fatalf("CheckUser returned a disabled user: %+v", got)
	}
}
