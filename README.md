# B2B Outbound OS — Self-Hosted B2B Outbound System (Free Demo Build)

**Demo login:** `demo@demo.com` / `demo123456`
**Live demo (nothing to install):** https://demo.goprospectflow.com/
**This repository contains the complete application source, plus a sample workspace.**

A self-hosted B2B outbound system for turning sales knowledge and customer lists
into a repeatable sales process. A customer list tells you who exists — this turns
it into a process that knows what to do next.

**Knowledge → ICP → Research → Scoring → Strategy → Outreach → Follow-up → Sample / Quote**

Build the system's knowledge of your products, ICP, buyer personas, industry
knowledge, buying signals and sales rules. Then research each account, score it
against your ICP, decide how to approach it, and follow the opportunity through
outreach, sample, quote and close.

**AI does not operate in a vacuum.** It uses your sales knowledge, ICP and account
context to make downstream decisions — research, scoring, strategy and messaging
all run on top of what you taught the system. The AI is the reasoning layer, not
the product.

**Not an email blaster.** It is the workflow layer that sits in front of your own
mailboxes and keeps your team moving customers forward.

## What ships in this build

- The complete application source (Python + FastAPI, SQLite, no build step)
- A realistic sample workspace: **81 demo companies** across 14 countries, 170+
  email interactions, 22 deals, 60 scheduled touches and a pre-filled knowledge
  base — companies, contacts and interactions are all fictional
- Five demo users (1 owner + 4 sales reps), so the team view has something to show
- One-click installers for Windows / macOS / Linux
- Sample data you can restore at any time from **System Settings → Reset demo data**

Self-hosted, your own mailbox, your own AI key, no telemetry, no accounts on our
servers. Your data never leaves your machine.

## Screenshots

| Today Workbench | Customer List | Follow-up Tasks |
|---|---|---|
| ![](docs/screenshots/today.png) | ![](docs/screenshots/list.png) | ![](docs/screenshots/reminders.png) |

| Email Center | Deals & Orders | Knowledge Base |
|---|---|---|
| ![](docs/screenshots/email.png) | ![](docs/screenshots/deals.png) | ![](docs/screenshots/knowledge.png) |

| Data Analytics | System Settings | |
|---|---|---|
| ![](docs/screenshots/analytics.png) | ![](docs/screenshots/setup.png) | |

## Quick start

**Requirements:** Python **3.10** (free) — nothing else.

1. Install Python 3.10 from https://www.python.org/downloads/ and tick
   *"Add python.exe to PATH"* during setup.
2. Download or clone this repository.
3. Windows: double-click `install.bat`, then `start.bat`.
   macOS / Linux: run `bash install_mac.sh`, then `bash start.sh`.
4. Your browser opens on http://localhost:8010 — log in with
   `demo@demo.com` / `demo123456`.

`start.bat` also installs the Python dependencies if you skip `install.bat`.

## What's inside

1. **Knowledge base — the system brain, not another feature.** Products, ICP,
   buyer personas, industry knowledge, buying signals and sales rules in one
   place. Everything downstream reads from it.
2. **ICP definition** — what a high-value customer looks like for you, and what
   to exclude.
3. **Account research** — website and business model, products and applications,
   LinkedIn and hiring signals, decision roles, relevant business signals.
4. **Explainable scoring** — 0–100 against your ICP with the reasons visible:
   what fits, what is missing, which tier it lands in.
5. **Development strategy** — who to approach, why now, what angle, which
   channel, what the next action is.
6. **Outreach execution** — multi-step plans with decision-chain ordering,
   across email, LinkedIn and WhatsApp on one customer path.
7. **Follow-up engine** — no-reply rules and cooling periods, so nothing gets
   dropped.
8. **Sample / quote / close** — deals pipeline, sample tracking, quote history
   and an email center that runs on your own mailbox.

## Add your own AI key

The demo starts without any API key, so the AI is off until you switch it on.
Put your own key in **System Settings → AI configuration** (Gemini, DeepSeek or
OpenAI — one is enough), restart, and the reasoning layer starts working **on the
demo data**: research, scoring, strategy, message generation, reply-intent
analysis and AI quote extraction — all driven by the knowledge you entered.

Your key stays in the local `.env` file; the model bills you directly at provider
prices (usually cents per campaign). There is no fee from us and no markup.

## First-time configuration

Open **System Settings** and work through the wizard — in this order, because
everything downstream depends on it:

1. **Company info** — name, your name, email, website
2. **AI configuration** — any one of Gemini / DeepSeek / OpenAI
3. **Sending mailbox (SMTP)** — e.g. Gmail with an app password
4. **Receiving mailbox (IMAP)** — same mailbox, used to fetch replies
5. **Knowledge base** — this is where the process starts. Enter your
   **products, ideal customer profile (ICP), buyer personas, industry knowledge,
   buying signals and sales rules.** The system uses them for research, scoring,
   strategy and every message it writes.

AI and mailbox changes take effect after restarting the system.

### Using Gmail

Enable IMAP in Gmail settings and create an app password (2-step verification is
required). Use:

- SMTP server `smtp.gmail.com`, port `465`
- IMAP server `imap.gmail.com`, port `993`

Paste the 16-character app password, not your normal Gmail password.

## Privacy & keys

- No API keys are bundled. You supply your own and pay the provider directly.
- SMTP / IMAP / AI keys live only in the local `.env` file on your machine.
- The app only touches the network when it deliberately sends or receives email,
  or calls the AI provider you configured. No telemetry, nothing phones home.
- The full source is in this repository, so you (or your developer) can read
  exactly what it does before connecting a mailbox or an AI key.

## Demo build vs. commercial license

| | This demo build | Commercial license — USD 99 one-time |
|---|---|---|
| Application source | ✅ | ✅ |
| Sample workspace | ✅ | clean, empty workspace |
| Knowledge-driven research, scoring, strategy | ✅ | ✅ |
| Evaluation and personal use | ✅ | ✅ |
| Production / business use | ❌ needs a license | ✅ |
| Illustrated English setup guide | — | ✅ |
| AI install / update prompts for Codex & Claude Code | — | ✅ |
| Updates for 1 year + setup support | — | ✅ |

One payment, no subscription, no renewal, team seats included.

**Buy the commercial license:** https://crmlokal.gumroad.com/

## License

Business Source License 1.1 (BSL 1.1) — see [LICENSE](LICENSE) for the full text.

In short:

- Free to read, run, modify and evaluate, free for personal or internal
  non-commercial use, and you may redistribute the unmodified build at no charge.
- **Production or commercial use** (running it for a business, reselling it, or
  charging for hosting or setup) requires the one-time **USD 99** commercial
  license: https://crmlokal.gumroad.com/
- On **2030-01-01** this project automatically converts to the
  **Apache License 2.0**.

## FAQ

**Is this really free?**
Yes — this build is free to download, run and evaluate. A commercial license
(USD 99 one-time) is required if you run it in a business.

**Do I need to be technical?**
No. Install Python 3.10, double-click two files, and you are in. The paid version
adds an illustrated guide plus one-prompt installers for Codex / Claude Code.

**Do I have to write prompts for the AI?**
No. You fill in your knowledge base once — products, ICP, buyer personas, buying
signals, sales rules — and the system uses it for research, scoring, strategy and
messaging. You can edit any AI draft before it is sent.

**Which email providers work?**
Any SMTP/IMAP mailbox: Gmail (app password), Outlook, Zoho, your company mail.

**What does the AI cost?**
You bring your own Gemini / DeepSeek / OpenAI key and pay the provider directly —
usually a few cents per campaign. There are no fees from us.

**Where is my data?**
In a local SQLite database next to the app, on your own machine. Backups are local
too, and can be encrypted.

**Is the demo data real?**
No. Every company, contact and interaction in the sample workspace is fictional
and generated for demonstration.

## Support & contact

- Website: https://goprospectflow.com
- Email: support@goprospectflow.com
- Questions and bug reports: please open an issue in this repository

## Contributing & changelog

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).
