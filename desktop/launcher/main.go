// Author's Hand desktop launcher.
//
// Double-clicking AuthorsHand.exe:
//  1. shows a setup/splash window (Edge "app" window, no browser bars),
//  2. on first run installs a private Python + the app's packages with the bundled uv.exe
//     (into %LOCALAPPDATA%\AuthorsHand — nothing is installed system-wide, no admin rights),
//  3. starts the Author's Hand engine on 127.0.0.1 and switches the window to it,
//  4. closes everything when the window is closed (or "Close app" is pressed).
//
// Standard library only. Build:  GOOS=windows GOARCH=amd64 go build -ldflags "-H windowsgui -s -w"
package main

import (
	"bufio"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"
)

const appName = "AuthorsHand"       // folder / file names
const displayName = "Author's Hand" // shown to the user

type state struct {
	mu      sync.Mutex
	Stage   string   `json:"stage"`
	Detail  string   `json:"detail"`
	Percent int      `json:"percent"`
	Ready   bool     `json:"ready"`
	URL     string   `json:"url"`
	Error   string   `json:"error"`
	Lines   []string `json:"lines"`
}

func (s *state) set(stage, detail string, pct int) {
	s.mu.Lock()
	s.Stage, s.Detail, s.Percent = stage, detail, pct
	s.mu.Unlock()
	log.Printf("[%d%%] %s — %s", pct, stage, detail)
}

func (s *state) line(l string) {
	l = strings.TrimSpace(l)
	if l == "" {
		return
	}
	s.mu.Lock()
	s.Lines = append(s.Lines, l)
	if len(s.Lines) > 8 {
		s.Lines = s.Lines[len(s.Lines)-8:]
	}
	s.mu.Unlock()
	log.Println("  " + l)
}

func (s *state) fail(msg string) {
	s.mu.Lock()
	s.Error = msg
	s.mu.Unlock()
	log.Println("ERROR: " + msg)
}

func (s *state) json() []byte {
	s.mu.Lock()
	defer s.mu.Unlock()
	b, _ := json.Marshal(s)
	return b
}

var (
	st        = &state{Stage: "Starting", Percent: 2}
	appDir    string // folder that contains AuthorsHand.exe
	dataDir   string // %LOCALAPPDATA%\AuthorsHand
	engine    *exec.Cmd
	browser   *exec.Cmd
	quitOnce  sync.Once
	quitCh    = make(chan struct{})
	splashURL string
)

func main() {
	exe, _ := os.Executable()
	appDir = filepath.Dir(exe)
	dataDir = filepath.Join(localAppData(), appName)
	_ = os.MkdirAll(dataDir, 0o755)
	lf, err := os.OpenFile(filepath.Join(dataDir, "launcher.log"), os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o644)
	if err == nil {
		log.SetOutput(io.MultiWriter(lf, os.Stdout))
	}
	log.Printf("%s launcher — app folder %s, data folder %s", displayName, appDir, dataDir)

	for _, a := range os.Args[1:] {
		if a == "--repair" {
			log.Println("Repair requested: removing private Python environment")
			_ = os.RemoveAll(filepath.Join(dataDir, "venv"))
			_ = os.Remove(filepath.Join(dataDir, "setup.ok"))
		}
	}

	// Single instance: if one is already running, just show its window.
	if url := runningInstance(); url != "" {
		openWindow(url, false)
		return
	}

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		log.Fatal(err)
	}
	splashURL = "http://" + ln.Addr().String() + "/"
	_ = os.WriteFile(filepath.Join(dataDir, "instance.json"), []byte(fmt.Sprintf(`{"url":%q,"pid":%d}`, splashURL, os.Getpid())), 0o644)
	go serve(ln)

	ensureShortcuts()
	go func() {
		if err := setupAndRun(); err != nil {
			st.fail(err.Error())
		}
	}()
	openWindow(splashURL, true)
	<-quitCh
	shutdown()
}

// ---------------------------------------------------------------- web splash
func serve(ln net.Listener) {
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write([]byte(splashHTML))
	})
	mux.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Access-Control-Allow-Origin", "*")
		_, _ = w.Write(st.json())
	})
	mux.HandleFunc("/retry", func(w http.ResponseWriter, r *http.Request) {
		st.mu.Lock()
		busy := st.Error == "" && !st.Ready
		st.Error, st.Lines = "", nil
		st.mu.Unlock()
		if !busy {
			go func() {
				if err := setupAndRun(); err != nil {
					st.fail(err.Error())
				}
			}()
		}
		_, _ = w.Write([]byte("ok"))
	})
	mux.HandleFunc("/log", func(w http.ResponseWriter, r *http.Request) {
		http.ServeFile(w, r, filepath.Join(dataDir, "launcher.log"))
	})
	mux.HandleFunc("/quit", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write([]byte(`<html><body style="font-family:Segoe UI,Arial;background:#0b1f33;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0"><div><h2>Author&#39;s Hand closed</h2><p>Your projects are saved. You can close this window.</p></div></body></html>`))
		go func() { time.Sleep(600 * time.Millisecond); requestQuit() }()
	})
	_ = http.Serve(ln, mux)
}

func requestQuit() { quitOnce.Do(func() { close(quitCh) }) }

func runningInstance() string {
	b, err := os.ReadFile(filepath.Join(dataDir, "instance.json"))
	if err != nil {
		return ""
	}
	var inst struct {
		URL string `json:"url"`
	}
	if json.Unmarshal(b, &inst) != nil || inst.URL == "" {
		return ""
	}
	c := http.Client{Timeout: 2 * time.Second}
	resp, err := c.Get(inst.URL + "status")
	if err != nil {
		return ""
	}
	defer resp.Body.Close()
	var s struct {
		Ready bool   `json:"ready"`
		URL   string `json:"url"`
	}
	_ = json.NewDecoder(resp.Body).Decode(&s)
	if s.Ready && s.URL != "" {
		return s.URL
	}
	return inst.URL
}

// ------------------------------------------------------------- setup & engine
func setupAndRun() error {
	app := filepath.Join(appDir, "app")
	req := filepath.Join(app, "requirements-desktop.txt")
	uv := filepath.Join(appDir, "runtime", exeName("uv"))
	venv := filepath.Join(dataDir, "venv")
	py := venvPython(venv)
	stamp := filepath.Join(dataDir, "setup.ok")
	want := fileHash(req)

	env := append(os.Environ(),
		"UV_PYTHON_INSTALL_DIR="+filepath.Join(dataDir, "python"),
		"UV_CACHE_DIR="+filepath.Join(dataDir, "uv-cache"),
		"UV_NATIVE_TLS=1", // trust the Windows certificate store (university / corporate proxies)
		"UV_HTTP_TIMEOUT=180",
		"UV_NO_PROGRESS=1",
	)

	have, _ := os.ReadFile(stamp)
	if strings.TrimSpace(string(have)) != want || !exists(py) {
		if !exists(uv) {
			return fmt.Errorf("runtime\\uv.exe is missing — re-extract the AuthorsHand zip")
		}
		st.set("First-time setup (only once)", "Downloading a private copy of Python 3.12…", 8)
		err := run(env, uv, "venv", "--python", "3.12", "--python-preference", "only-managed", "--seed", venv)
		if err != nil {
			st.line("Managed Python download failed — trying a Python already on this computer")
			st.set("First-time setup (only once)", "Looking for Python installed on this computer…", 12)
			err = run(env, uv, "venv", "--python-preference", "only-system", "--seed", venv)
		}
		if err != nil {
			return fmt.Errorf("could not prepare Python (%v). Check the internet connection and press Retry", err)
		}
		st.set("First-time setup (only once)", "Installing research libraries (about 250 MB, 2–6 minutes)…", 25)
		go creep(25, 85, 6*time.Minute)
		if err := run(env, uv, "pip", "install", "--python", py, "-r", req); err != nil {
			return fmt.Errorf("installing libraries failed (%v). Check the internet connection and press Retry", err)
		}
		_ = os.WriteFile(stamp, []byte(want), 0o644)
	}

	st.set("Starting "+displayName, "Opening your research workspace…", 90)
	port := preferredPort(8765) // fixed port so Google/ORCID sign-in redirect URLs stay valid
	docs := filepath.Join(userHome(), "Documents", appName)
	_ = os.MkdirAll(docs, 0o755)
	// keep the library of an earlier ScholarPilot install
	oldDB := filepath.Join(userHome(), "Documents", "ScholarPilot", "workspace.db")
	newDB := filepath.Join(docs, "workspace.db")
	if exists(oldDB) && !exists(newDB) {
		if b, err := os.ReadFile(oldDB); err == nil {
			_ = os.WriteFile(newDB, b, 0o644)
			log.Println("migrated library from Documents\\ScholarPilot")
		}
	}
	engine = exec.Command(py, "-m", "streamlit", "run", filepath.Join(app, "app.py"),
		"--server.port", fmt.Sprint(port), "--server.address", "127.0.0.1", "--server.headless", "true",
		"--browser.gatherUsageStats", "false", "--global.developmentMode", "false",
		"--client.toolbarMode", "viewer", "--server.fileWatcherType", "none")
	engine.Dir = app
	_ = writeAuthSecrets(app, port)
	engine.Env = append(env,
		"AUTHORSHAND_DB="+filepath.Join(docs, "workspace.db"),
		"AUTHORSHAND_LAUNCHER_URL="+splashURL,
		"AUTHORSHAND_DESKTOP=1",
		"AUTHORSHAND_DATA_DIR="+dataDir,
		"PYTHONUTF8=1",
	)
	hideWindow(engine)
	out, _ := engine.StdoutPipe()
	engine.Stderr = engine.Stdout
	if err := engine.Start(); err != nil {
		return fmt.Errorf("could not start the engine: %v", err)
	}
	go pipeLines(out)
	go func() {
		_ = engine.Wait()
		log.Println("engine exited")
	}()
	url := fmt.Sprintf("http://127.0.0.1:%d", port)
	for i := 0; i < 240; i++ {
		resp, err := http.Get(url + "/_stcore/health")
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == 200 {
				st.mu.Lock()
				// The window opens on "localhost" so the Google / ORCID sign-in redirect
				// (http://localhost:PORT/oauth2callback) and the sign-in cookie use the same host.
				appURL := fmt.Sprintf("http://localhost:%d", port)
				st.Ready, st.URL, st.Percent, st.Stage = true, appURL, 100, "Ready"
				st.mu.Unlock()
				log.Println("engine ready at " + appURL)
				return nil
			}
		}
		time.Sleep(500 * time.Millisecond)
	}
	return fmt.Errorf("the engine did not start in 2 minutes — see the log")
}

func creep(from, to int, over time.Duration) {
	steps := to - from
	for i := 0; i < steps; i++ {
		time.Sleep(over / time.Duration(steps))
		st.mu.Lock()
		if st.Percent >= to || st.Ready || st.Error != "" || !strings.HasPrefix(st.Stage, "First-time") {
			st.mu.Unlock()
			return
		}
		st.Percent++
		st.mu.Unlock()
	}
}

func run(env []string, name string, args ...string) error {
	cmd := exec.Command(name, args...)
	cmd.Env = env
	hideWindow(cmd)
	out, _ := cmd.StdoutPipe()
	cmd.Stderr = cmd.Stdout
	log.Printf("run: %s %s", name, strings.Join(args, " "))
	if err := cmd.Start(); err != nil {
		return err
	}
	pipeLines(out)
	return cmd.Wait()
}

func pipeLines(r io.Reader) {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 64*1024), 1024*1024)
	for sc.Scan() {
		st.line(sc.Text())
	}
}

// ------------------------------------------------------------------ window
func openWindow(url string, wait bool) {
	profile := filepath.Join(dataDir, "window-profile")
	args := []string{"--app=" + url, "--user-data-dir=" + profile, "--no-first-run", "--no-default-browser-check",
		"--window-size=1440,920", "--disable-features=Translate"}
	for _, b := range browserCandidates() {
		if !exists(b) {
			continue
		}
		browser = exec.Command(b, args...)
		if err := browser.Start(); err == nil {
			log.Println("window: " + b)
			if wait {
				go func() {
					_ = browser.Wait()
					log.Println("window closed")
					requestQuit()
				}()
			}
			return
		}
	}
	// Fallback: default browser. The app stays open until "Close app" is pressed.
	log.Println("no Edge/Chrome found; using the default browser")
	openDefault(url)
}

func browserCandidates() []string {
	if runtime.GOOS == "windows" {
		var c []string
		for _, base := range []string{os.Getenv("ProgramFiles(x86)"), os.Getenv("ProgramFiles"), os.Getenv("LOCALAPPDATA")} {
			if base == "" {
				continue
			}
			c = append(c, filepath.Join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
				filepath.Join(base, "Google", "Chrome", "Application", "chrome.exe"))
		}
		return c
	}
	return []string{"/usr/bin/microsoft-edge", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"}
}

func shutdown() {
	log.Println("shutting down")
	if engine != nil && engine.Process != nil {
		_ = engine.Process.Kill()
	}
	if browser != nil && browser.Process != nil {
		_ = browser.Process.Kill()
	}
	_ = os.Remove(filepath.Join(dataDir, "instance.json"))
	time.Sleep(300 * time.Millisecond)
}

// ----------------------------------------------------------------- helpers
func exists(p string) bool { _, err := os.Stat(p); return err == nil }

func fileHash(p string) string {
	b, err := os.ReadFile(p)
	if err != nil {
		return "missing"
	}
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}

func freePort() int {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return 8501
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port
}

func preferredPort(p int) int {
	l, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", p))
	if err != nil {
		return freePort()
	}
	l.Close()
	return p
}

// writeAuthSecrets copies sign-in provider settings saved in the app (auth.json in the data
// folder) into .streamlit/secrets.toml with the redirect URL for this port.
func writeAuthSecrets(app string, port int) error {
	src := filepath.Join(dataDir, "auth.toml")
	b, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	txt := strings.ReplaceAll(string(b), "{PORT}", fmt.Sprint(port))
	_ = os.MkdirAll(filepath.Join(app, ".streamlit"), 0o755)
	return os.WriteFile(filepath.Join(app, ".streamlit", "secrets.toml"), []byte(txt), 0o600)
}

func exeName(n string) string {
	if runtime.GOOS == "windows" {
		return n + ".exe"
	}
	return n
}

func venvPython(v string) string {
	if runtime.GOOS == "windows" {
		return filepath.Join(v, "Scripts", "python.exe")
	}
	return filepath.Join(v, "bin", "python")
}

func localAppData() string {
	if d := os.Getenv("LOCALAPPDATA"); d != "" {
		return d
	}
	d, _ := os.UserCacheDir()
	return d
}

func userHome() string { h, _ := os.UserHomeDir(); return h }
