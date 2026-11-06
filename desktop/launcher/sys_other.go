//go:build !windows

package main

import "os/exec"

func hideWindow(c *exec.Cmd) {}

func openDefault(url string) { _ = exec.Command("xdg-open", url).Start() }

func ensureShortcuts() {}
