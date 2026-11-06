//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
)

const createNoWindow = 0x08000000

func hideWindow(c *exec.Cmd) {
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}
}

func openDefault(url string) {
	c := exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	hideWindow(c)
	_ = c.Start()
}

// ensureShortcuts creates Desktop and Start-menu shortcuts once (no admin rights needed).
func ensureShortcuts() {
	marker := filepath.Join(dataDir, "shortcuts.ok")
	exe, _ := os.Executable()
	if b, err := os.ReadFile(marker); err == nil && string(b) == exe {
		return
	}
	icon := filepath.Join(appDir, "AuthorsHand.ico")
	q := func(v string) string { return strings.ReplaceAll(v, "'", "''") }
	ps := fmt.Sprintf(`$s=New-Object -ComObject WScript.Shell;`+
		`foreach($d in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))){`+
		`$l=$s.CreateShortcut((Join-Path $d 'Author''s Hand.lnk'));$l.TargetPath='%s';$l.WorkingDirectory='%s';`+
		`$l.IconLocation='%s';$l.Description='Author''s Hand research workspace';$l.Save()}`, q(exe), q(appDir), q(icon))
	c := exec.Command("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps)
	hideWindow(c)
	if err := c.Run(); err == nil {
		_ = os.WriteFile(marker, []byte(exe), 0o644)
	}
}
