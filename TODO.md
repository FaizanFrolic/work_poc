# 🛡️ Security & Privacy Roadmap (TODO)

This document tracks identified security enhancements and privacy improvements for the Data Submission App. These should be addressed before moving the application from POC to production.

---

### **1. Authentication & Session Management**
- [ ] **Secure Admin Account:** 
    - [ ] Change the default `password123` to a secure, randomly generated initial password.
    - [ ] Force a password change on first login for the `admin` user.
- [ ] **Remove Session Tokens from URL:**
    - [ ] Currently, the session token is stored in the browser's URL using `st.query_params`. 
    - [ ] *Risk:* Tokens can be leaked via browser history, server logs, or screenshots.
    - [ ] *Fix:* Rely on Streamlit's internal `st.session_state` and investigate secure, HTTP-only cookies for persistence.
- [ ] **Session Expiry Enforcement:**
    - [ ] Implement a logic to automatically log users out after a period of inactivity (idle timeout).

### **2. AI Data Privacy (PII)**
- [ ] **Data Anonymization Layer:**
    - [ ] Before sending data to LLM providers (Gemini, OpenAI, Groq, etc.), implement a scrubber to mask potential Personally Identifiable Information (PII).
    - [ ] *Examples:* Mask emails, phone numbers, and specific names in `DataA`-`DataD` fields.
- [ ] **Opt-In AI Features:**
    - [ ] Allow users to explicitly consent to their data being processed by external AI providers.

### **3. Database & Storage Security**
- [ ] **Encrypted Cache:**
    - [ ] The `ai_insights_cache` table currently stores AI summaries in plain text.
    - [ ] *Fix:* Encrypt sensitive cached insights using a server-side master key.
- [ ] **Database Backups:**
    - [ ] While Cloud Sync exists, implement an automated local backup strategy for `submissions.db`.
- [ ] **Environment Secret Management:**
    - [ ] Move all sensitive keys (Google API, OpenAI, etc.) to a secure environment file (`.env`) or a dedicated secret management service.

### **4. Logging & Monitoring**
- [ ] **Enhanced Audit Logs:**
    - [ ] Log failed login attempts and unauthorized access attempts.
    - [ ] Include IP addresses and browser fingerprints in the `audit_logs` for better forensics.

---

*Last Updated: March 14, 2026*
