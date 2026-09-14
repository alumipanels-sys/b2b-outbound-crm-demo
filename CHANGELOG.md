# Changelog

## [1.0.5] - 2026-09-14

### Changed

- **Positioning aligned with the website.** B2B Outbound OS is a self-hosted
  B2B outbound *system* — Knowledge → ICP → Research → Scoring → Strategy →
  Outreach → Follow-up → Sample / Quote — not "another self-hosted CRM".
- **README restructured:** the knowledge base is now presented as the starting
  point of the system (the system brain), and AI is framed as the reasoning
  layer that runs on your sales knowledge, ICP and account context.
- **Brand:** the old name is gone from code, scripts, documents and emails;
  everything is now B2B Outbound OS. Contact address is
  support@goprospectflow.com and the project lives under the `b2boutbound`
  account.
- **AI module ships as readable source** (PyArmor removed), so the whole
  application can be reviewed before connecting a mailbox or an AI key.
- **Windows launcher added** (`start.bat`); the installer no longer references a
  missing file.

## [1.0.4] - 2026-09-08

### Changed

- Official website: **https://goprospectflow.com** added across README,
  license and support channels.
- README screenshots replaced with true 2x (3200x2000) captures of every page
  (Today, Customer List, Follow-up Tasks, Email Center, Deals & Orders,
  Knowledge Base, Data Analytics, System Settings).
- README screenshot gallery expanded to 8 pages (added Data Analytics and
  System Settings).

## [1.0.3] - 2026-09-07

### Changed

- Packaging and distribution updates.

## [1.0.2] - 2026-09-07

### Added

- Follow-up reasons: every scheduled touch on the Today board now shows why
  it is due (follow-up #2 after days of silence, a fresh reply that needs a
  response, cooling re-review, etc.)
- Cooling review cards keep the original cooling-day line, with the reason
  shown as an additional line (additive, nothing removed).

## [1.0.1] - 2026-09-07

### Added

- Gumroad checkout for the $99 full version:
  https://crmlokal.gumroad.com/l/ProspectFlow

## [1.0.0] - 2026-09-07

Initial English community demo release.

### Added

- Full self-hosted export-sales outreach system (customers, AI scoring,
  outreach plans, email center, deals, follow-up engine, knowledge base,
  team dashboard, backups)
- English demo data reset (81 fictional customers across sales stages)
- One-click installers: `install.bat` (Windows) and `install_mac.sh`
  (macOS / Linux) with Python 3.10 version checks
- README with screenshots, value props and $99 one-time full-version offer
- GitHub Topics and SEO-friendly description
