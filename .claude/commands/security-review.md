---
allowed-tools: Bash(git diff:*), Bash(git status:*), Bash(git log:*), Bash(git show:*), Bash(git remote show:*), Read, Glob, Grep, LS, Task
description: Security review of pending changes using CWE-based checklists, data-flow analysis, and confidence-gated verification
---

You are a senior security engineer conducting a focused security review of the changes on this branch. Assume an attacker mindset — think about bypasses, edge cases, and exploitation chains.

GIT STATUS:

```
!`git status`
```

FILES MODIFIED:

```
!`git diff --name-only origin/HEAD...`
```

COMMITS:

```
!`git log --no-decorate origin/HEAD...`
```

DIFF CONTENT:

```
!`git diff --merge-base origin/HEAD`
```

Review the complete diff above. This contains all code changes in the PR.

---

# OBJECTIVE

Perform a security-focused code review to identify HIGH-CONFIDENCE security vulnerabilities with real exploitation potential. This is not a general code review — focus ONLY on security implications newly added by this PR. Do not comment on pre-existing security concerns.

# CRITICAL INSTRUCTIONS

1. MINIMIZE FALSE POSITIVES: Only flag issues where you are >80% confident of actual exploitability
2. AVOID NOISE: Skip theoretical issues, style concerns, or low-impact findings
3. FOCUS ON IMPACT: Prioritize vulnerabilities that could lead to unauthorized access, data breaches, or system compromise
4. ATTACKER MINDSET: For each finding, think about how an attacker would actually exploit it — what is the concrete attack path?
5. CITE CODE EVIDENCE: Every finding must reference specific file paths, line numbers, and code snippets

---

# PHASE 1 — REPOSITORY CONTEXT RESEARCH

Use file search and grep tools to understand the codebase before reviewing the diff:

- Identify the languages, frameworks, and libraries in use
- Look for existing security frameworks, sanitization patterns, and validation helpers
- Examine authentication/authorization middleware or decorators
- Understand the project's trust boundaries (what is user input vs trusted internal data?)
- Check for existing security configurations (CORS, CSP, security headers)

---

# PHASE 2 — SOURCE AND SINK IDENTIFICATION

Map the data flow using SpecterOps' source/sink taxonomy:

**Sources (untrusted input entry points):**
- HTTP parameters, query strings, route params
- Request bodies (JSON, form data, multipart)
- HTTP headers, cookies
- WebSocket messages
- Uploaded files and filenames
- URL paths
- Database records originating from user input
- Environment variables with user-controlled defaults

**Sinks (dangerous operations):**
- Database queries (SQL, Cypher, NoSQL)
- OS command execution (subprocess, exec, system)
- File system operations (open, read, write, path construction)
- Code execution (eval, exec, Function, pickle.loads, yaml.load)
- Template rendering (render_template_string, Template())
- Deserialization (pickle, ObjectInputStream, unserialize, yaml.load)
- Authentication/authorization decisions
- External API calls and URL construction
- HTML output (innerHTML, dangerouslySetInnerHTML, document.write)
- Cloud storage operations

For each modified file, trace data flow: Source -> Transform -> Sink. Flag any path where untrusted input reaches a dangerous sink without adequate sanitization.

---

# PHASE 3 — CWE-BASED VULNERABILITY CHECKLIST

Scan each modified file against the following checklist, organized by the most actively exploited vulnerability classes (per CISA KEV 2024-2025 and OWASP 2025):

## Priority 1: Most Exploited in the Wild (CISA KEV Top 5)

### CWE-78: OS Command Injection
**Search patterns:** `os.system(`, `subprocess.call(.*shell=True`, `subprocess.run(.*shell=True`, `exec.Command("sh"`, `Runtime.exec(`, `system(`
**Dangerous:** User input concatenated into shell commands
**Safe:** Parameterized command arrays with `shell=False`

```python
# VULNERABLE
os.system("ping " + user_input)
subprocess.run(f"grep {query} /var/log/app.log", shell=True)

# SECURE
subprocess.run(["ping", "-c", "1", validated_host], shell=False)
```

### CWE-502: Deserialization of Untrusted Data
**Search patterns:** `pickle.loads(`, `pickle.load(`, `yaml.load(` (without SafeLoader), `ObjectInputStream`, `.readObject()`, `unserialize(`
**Dangerous:** Deserializing data from any untrusted source
**Safe:** JSON parsing, yaml.safe_load, whitelisted class deserialization

```python
# VULNERABLE — arbitrary code execution
obj = pickle.loads(request.get_data())
data = yaml.load(user_input)

# SECURE
data = json.loads(request.get_data())
data = yaml.safe_load(user_input)
```

### CWE-22: Path Traversal
**Search patterns:** `os.path.join` with user input, `filepath.Join`, `open(` with user input, `new File(base + input)`, `../`
**Critical note:** `os.path.join('/base', '/etc/passwd')` returns `/etc/passwd` — absolute paths replace the base!

```python
# VULNERABLE
path = os.path.join(upload_dir, user_filename)

# SECURE
base = os.path.realpath('/var/uploads')
path = os.path.realpath(os.path.join(base, filename))
if not path.startswith(base + os.sep):
    raise SecurityError("Path traversal detected")
```

### CWE-89: SQL Injection
**Search patterns:** `cursor.execute(f"`, `cursor.execute("SELECT.*" +`, `%s" %`, string concat near `SELECT/INSERT/UPDATE/DELETE`, `f"SELECT`, `fmt.Sprintf` with SQL, `createStatement()`, `.executeQuery(` with string concat
**Dangerous:** String interpolation/concatenation in SQL
**Safe:** Parameterized queries

```python
# VULNERABLE
cursor.execute(f"SELECT * FROM users WHERE name = '{username}'")

# SECURE
cursor.execute("SELECT * FROM users WHERE name = %s", (username,))
```

### CWE-416 / CWE-787: Memory Safety (C/C++ only)
**Search patterns:** `gets(`, `strcpy(`, `strcat(`, `sprintf(`, `free(` without NULL assignment
**Skip:** Memory-safe languages (Rust safe code, Python, JS, Go, Java)

## Priority 2: OWASP 2025 Top 10 + CWE Top 25

### CWE-79: Cross-Site Scripting (XSS)
**Search patterns:** `.innerHTML =`, `dangerouslySetInnerHTML`, `document.write(`, `v-html`, `text/template` (Go), `render_template_string(`
**Framework-safe:** React JSX `{variable}` auto-escapes. Angular templates auto-escape. Only flag if using unsafe bypass methods.

```javascript
// VULNERABLE
element.innerHTML = userInput;
<div dangerouslySetInnerHTML={{__html: userInput}} />

// SECURE (React auto-escapes)
<div>{userInput}</div>
element.textContent = userInput;
```

### CWE-862/CWE-863: Broken Access Control (OWASP A01)
**Check:** Every data-access endpoint verifies object ownership
**Search patterns:** `findById(req.params.id)` without ownership check, missing authorization middleware on sensitive routes
**Look for:** IDOR — direct object references without verifying the authenticated user owns the resource

### CWE-94: Code Injection / eval()
**Search patterns:** `eval(`, `exec(`, `new Function(`, `setTimeout(` with string arg
**Dangerous:** User input reaching eval/exec
**Safe:** `ast.literal_eval()`, `JSON.parse()`

```python
# VULNERABLE
result = eval(request.args.get('expr'))

# SECURE
result = ast.literal_eval(user_input)
```

### CWE-918: Server-Side Request Forgery (SSRF)
**Search patterns:** `requests.get(` with user-controlled URLs, `fetch(` with user URLs, `urllib.urlopen(`
**Only flag if:** Attacker can control the host or protocol (path-only control is NOT SSRF)

```python
# VULNERABLE — can hit internal metadata endpoints
resp = requests.get(request.args.get('url'))

# SECURE
ip = socket.gethostbyname(parsed.hostname)
if ipaddress.ip_address(ip).is_private:
    raise SecurityError("Private IP blocked")
```

### CWE-434: Unrestricted File Upload
**Check:** File type validation (not just extension), file size limits, safe storage location, filename sanitization

### CWE-352: Cross-Site Request Forgery (CSRF)
**Check:** State-changing operations require CSRF tokens or use SameSite cookies

### CWE-798: Hardcoded Credentials
**Search patterns (regex):**
- AWS: `(A3T[A-Z0-9]|AKIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}`
- Private keys: `-----BEGIN (RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----`
- GitHub PAT: `ghp_[0-9a-zA-Z]{36}`
- Slack: `xox[baprs]-[0-9]{10,13}-[0-9a-zA-Z]{10,48}`
- Stripe: `sk_live_[0-9a-zA-Z]{24,99}`
- Google: `AIza[0-9A-Za-z\-_]{35}`
- Generic: `(?i)(password|passwd|secret|token|api_key|apikey|access_key|auth)(.{0,20})?['"][0-9a-zA-Z]{10,}`
- Database URIs: `(?i)(mongodb(\+srv)?|mysql|postgres(ql)?|redis|mssql):\/\/[^\s'"]{10,}`
- Basic auth in URL: `https?://[^:]+:[^@]+@[^\s/]+`

**Also check:** Shannon entropy — Base64 strings with entropy > 4.5 and hex strings with entropy > 3.0 are likely secrets
**Common hiding places:** `.env` files, config defaults, `os.getenv("SECRET", "hardcoded_default")`, test fixtures, Docker ENV, CI configs

## Priority 3: Authentication, Crypto, and API Security

### JWT Vulnerabilities
- **Algorithm none attack:** `jwt.verify(token, secret)` without `{ algorithms: ["HS256"] }`
- **Algorithm confusion (RS256->HS256):** `jwt.decode` without explicit algorithm
- **Weak secrets:** JWT secret shorter than 32 characters, common values ("secret", "password", "123456")
- **Missing expiry:** `jwt.sign(payload, secret)` without `expiresIn`

### Cryptography Anti-Patterns
1. **ECB mode:** `AES/ECB`, `AES.MODE_ECB`, `Cipher.getInstance("AES")` (Java defaults to ECB)
2. **Fixed IV/nonce:** Literal byte strings as IV, `b'\x00' * 16`, constants
3. **Non-constant-time comparison:** `==` on HMAC/token strings (use `hmac.compare_digest()` / `crypto.timingSafeEqual()` / `subtle.ConstantTimeCompare()`)
4. **Weak algorithms:** `DES`, `3DES`, `RC4`, `MD5`, `SHA1` for integrity or passwords
5. **Insecure randomness:** `Math.random()`, `new Random()` (Java), `random.random()` (Python) for tokens/sessions
6. **Disabled TLS:** `verify=False` (Python), `NODE_TLS_REJECT_UNAUTHORIZED='0'` (Node.js), `InsecureSkipVerify` (Go)
7. **Password as key:** Password used directly as encryption key without KDF (PBKDF2/scrypt/Argon2)

### CORS Misconfiguration
**Most dangerous:** Reflecting the Origin header back with `Access-Control-Allow-Credentials: true`
**Search for:** `Access-Control-Allow-Origin: *` combined with credentials, dynamic origin reflection

### Mass Assignment
**Search for:** `User.create(req.body)`, `db.update(id, req.body)` without field allowlisting
**Attack:** Attacker adds `isAdmin: true` or `role: "superadmin"` to request body

### GraphQL
- Introspection enabled in production
- No query depth limit (nest to 7-10 max)
- No batching limits (100+ mutations in one request bypasses rate limiting)

## Priority 4: Supply Chain and Infrastructure

### Supply Chain (OWASP A03 — new in 2025)
- **Lockfile integrity:** Resolved URLs should point to official registries, integrity hashes present
- **Typosquatting:** Adjacent keyboard letters, added/removed dashes, prefix/suffix variants, scope confusion
- **Malicious packages:** `preinstall`/`postinstall` scripts executing code, obfuscated source, network calls in install scripts

### Dockerfile Patterns
- `FROM image:latest` (unpinned base image)
- Missing `USER` directive (runs as root)
- `COPY . .` without `.dockerignore`
- `ENV SECRET=value` baking secrets into layers

### Terraform/Kubernetes
- **Terraform:** `Action = "*"` + `Resource = "*"` in IAM, `acl = "public-read"`, `cidr_blocks = ["0.0.0.0/0"]`, missing `storage_encrypted`
- **Kubernetes:** Missing `securityContext`, `privileged: true`, `hostPath` mounts to `/` or `/var/run/docker.sock`, missing `NetworkPolicy`, missing `resources.limits`

---

# PHASE 4 — SEMI-FORMAL REASONING FOR EACH FINDING

For each potential vulnerability, apply Meta's structured reasoning template (93% verification accuracy):

1. **Premises:** State what you observe in the code (exact lines, variable names, function calls)
2. **Execution Path Trace:** Trace how untrusted data flows from source to sink, noting each transformation
3. **Formal Conclusion:** Based on the trace, is this exploitable? What is the concrete attack scenario?

Only proceed to report a finding if the formal conclusion demonstrates a clear, concrete exploit path.

---

# REQUIRED OUTPUT FORMAT

Output findings in markdown. Each finding must include:

## Vuln N: [Category]: `file.py:line`

* **CWE:** CWE-XXX (Name)
* **Severity:** Critical | High | Medium
* **Confidence:** High (direct code evidence) | Medium (likely but depends on unseen code)
* **OWASP 2025:** A0X (if applicable)
* **Description:** What the vulnerability is and why it's dangerous
* **Vulnerable Code:**
```
<exact code snippet from the diff>
```
* **Data Flow:** Source (where untrusted input enters) -> Transform (any processing) -> Sink (dangerous operation)
* **Exploit Scenario:** Concrete, step-by-step attack scenario an attacker would follow
* **Recommendation:** Specific code fix with secure alternative

---

# SEVERITY CLASSIFICATION

Based on Microsoft SDL Bug Bar, CVSS v4.0, and OWASP:

**CRITICAL (block release):** Remote code execution without auth, SQL/command injection in production paths, hardcoded credentials in source, authentication bypass, deserialization of untrusted data, buffer overflow in remotely callable code

**HIGH (fix before release):** Stored XSS, SSRF with host control, XXE, path traversal with file read/write, missing authorization on sensitive endpoints, privilege escalation, weak crypto for passwords (MD5/SHA1), missing encryption for sensitive data in transit

**MEDIUM (fix in current sprint):** Reflected XSS, CSRF, session fixation, missing rate limiting on auth endpoints, verbose error messages with stack traces, missing security headers, information disclosure

Only report HIGH and MEDIUM findings minimum. CRITICAL findings should always be reported.

---

# CONFIDENCE SCORING

- **0.9-1.0:** Certain exploit path identified with direct code evidence
- **0.8-0.9:** Clear vulnerability pattern with known exploitation methods
- **0.7-0.8:** Suspicious pattern requiring specific conditions to exploit
- **Below 0.7:** Do not report (too speculative)

---

# FALSE POSITIVE FILTERING

## Hard Exclusions — Automatically skip findings matching these patterns:

1. Denial of Service (DoS), resource exhaustion, or rate limiting concerns
2. Secrets or credentials stored on disk if they are otherwise secured by file permissions
3. Memory safety issues in memory-safe languages (Rust safe code, Python, JS, Go, Java)
4. Race conditions or timing attacks that are theoretical rather than practically exploitable
5. Input validation concerns on non-security-critical fields without proven security impact
6. GitHub Action workflow issues unless clearly triggerable via untrusted input
7. Lack of hardening measures — only flag concrete vulnerabilities, not missing best practices
8. Outdated third-party library versions (managed separately)
9. Files that are only unit tests or only used for testing (unless they contain hardcoded production credentials)
10. Log spoofing — outputting unsanitized input to logs is not a vulnerability
11. SSRF that only controls the path (not host or protocol)
12. User-controlled content in AI system prompts is not a vulnerability
13. Regex injection or ReDoS concerns
14. Insecure documentation (markdown files, comments)
15. Missing audit logs
16. Vulnerabilities in `.ipynb` notebook files unless there is a very specific untrusted input attack path

## Precedents:

1. Logging high-value secrets in plaintext IS a vulnerability. Logging URLs is safe.
2. UUIDs are unguessable and do not need validation.
3. Environment variables and CLI flags are trusted values. Attacks requiring control of env vars are invalid.
4. Resource management issues (memory/FD leaks) are not valid findings.
5. React and Angular auto-escape user input. Only flag XSS if using `dangerouslySetInnerHTML`, `bypassSecurityTrustHtml`, or similar unsafe methods.
6. Client-side JS/TS code is not responsible for permission checking or authentication — the backend handles this.
7. Only include MEDIUM findings if they are obvious and concrete.
8. Command injection in shell scripts is generally not exploitable unless there is a concrete untrusted input path.
9. Logging non-PII data is not a vulnerability even if sensitive. Only flag if it exposes secrets, passwords, or PII.

---

# ANALYSIS EXECUTION

Execute this analysis in 3 steps using sub-tasks:

**Step 1 — Identify Candidates:**
Use a sub-task to scan all modified files against the CWE checklist above. For each file:
- Run mechanical pattern matching (search for dangerous function calls and patterns listed above)
- Perform intra-file data-flow analysis (trace parameters from function entry to dangerous sinks)
- Attempt limited cross-file analysis only where imports clearly indicate a data flow path
- Apply the semi-formal reasoning template to each candidate
Include all context from this prompt in the sub-task.

**Step 2 — Verify Each Finding (parallel):**
For each candidate vulnerability from Step 1, launch a parallel sub-task to independently verify:
- Is this a concrete, exploitable vulnerability with a clear attack path?
- Does this match any hard exclusion or precedent from the false positive list?
- Does the code evidence support the finding (exact lines, not hypothetical)?
- Would a security engineer confidently raise this in a PR review?
- Assign a confidence score from 1-10.

**Step 3 — Filter and Report:**
- Discard any finding where the verification sub-task reported confidence < 8
- Discard any finding matching a hard exclusion
- Compile remaining findings into the required output format
- Sort by severity (Critical > High > Medium)

Your final reply must contain only the markdown report. If no vulnerabilities meet the confidence threshold, state: "No high-confidence security vulnerabilities identified in this changeset."
