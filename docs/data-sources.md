# Data sources and redistribution

[MIT](../LICENSE) covers repository-authored code and original documentation. It does not relicense third-party data, quoted rules, trademarks, or external analyses. Presence in Git proves provenance, not redistribution permission.

| Material | Provenance and treatment |
|---|---|
| [Raw snapshots](../data/raw/) | OpenDota responses with chunk hashes and acquisition manifests; Steam news is listed separately below. No blanket dataset redistribution license established. Public release held pending applicable terms or written permission. |
| [Rules evidence](../data/evidence/) and quoted rules | Valve/Steam sources and owner-imported rendered text. Preserve attribution and manifests. Public release held pending an applicable redistribution basis; see the source register below. |
| [External analyses](../predictions-from-llms/) and cards | Vitalii Babenko confirms generating the analyses using Gemini, ChatGPT, and other unspecified services. File-specific service/account details, generation settings, and copied-material status remain unconfirmed. Public release held pending that review. |
| Derived reports | Repository-produced research, still subject to review of underlying data restrictions and incorporated quotations. |
| Dependencies | Separate upstream licenses apply. Review dependency notices before distributing bundled dependencies. |

Sources: [OpenDota core](https://github.com/odota/core), [Steam Web API terms](https://steamcommunity.com/dev/apiterms), [GitHub licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository). OpenDota's software license does not establish dataset rights.

## Source-permission register

Owner approval records a release decision; it cannot supply missing third-party rights. No written redistribution permission is recorded here yet. Attribution preserves provenance but does not itself authorize copying.

| Source and retained material | Terms reviewed and attribution | Publication decision / missing evidence |
|---|---|---|
| OpenDota API responses in timestamped `data/raw/` snapshots | [Core software MIT license](https://github.com/odota/core) does not establish API dataset rights. Retain OpenDota attribution, request provenance, acquisition manifests, and chunk hashes. Exact dataset attribution conditions remain unresolved. | **Hold.** Permission inquiry sent through the official Discord help channel; response pending. Ask whether underlying Valve restrictions apply to snapshots and player IDs. |
| [Dota rules page](https://www.dota2.com/esports/ti15/tirules): `data/evidence/imports/valve-group-stage-rendered.txt`, corresponding `data/evidence/rules/` captures, [archival text](ti26/2026-08-08-ti2026-rules-fetched.md), and [owner transcription](ti26/2026-08-08-published-format-rules.md) | Rendered-page capture/transcription, not an established Steam API response. Retain source URL, acquisition records, and embedded Valve copyright/trademark notice. [Valve legal page](https://www.valvesoftware.com/en/legal) restricts republication of its site material, but applicability to this Dota page is unconfirmed. | **Hold.** Identify governing Dota-page terms or obtain written permission for the retained verbatim text and duplicates. Steam API terms cannot be assumed to cover it. |
| [Steam announcement](https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/1840944183772671): [raw response](../data/raw/steam-news/1840944183772671.json), `data/evidence/imports/valve-ti2026-format-rendered.txt`, and matching `format-rendered.txt` capture | Acquired through `ISteamNews/GetNewsForApp/v2`; metadata attributes author `krAnk0r`. Preserve title, author, source/feed metadata, links, and capture manifests. [Steam API terms](https://steamcommunity.com/dev/apiterms) condition distribution on the application/use and include privacy, branding, disclaimer, and termination obligations. [Subscriber Agreement](https://store.steampowered.com/subscriber_agreement/) also reserves rights. | **Hold.** Confirm whether API terms cover this endpoint and permanent public Git archival, and how their conditions would be met. No unconditional MIT grant established. |
| [Gemini-named analysis](../predictions-from-llms/gemini-3-1-pro.md) | Owner confirms generating the supplied analyses with AI services; filename is not verified model provenance. Retain AI authorship disclosure and the works-cited list. [Google generative-AI terms](https://policies.google.com/terms/generative-ai) are a review starting point; account/product and applicable terms at generation remain unknown. | **Hold.** Record file-specific service/account provenance and whether prompts or outputs contain copied passages; review those sources separately. |
| [GPT-named analysis](../predictions-from-llms/gpt-5-6-xhigh.md) | Owner confirms generating the supplied analyses with AI services. Opaque citation markers lack persisted source URLs. [OpenAI terms](https://openai.com/policies/row-terms-of-use/) distinguish consumer, regional, and business use; output ownership does not grant third-party rights. Applicable account/region/version remains unknown. | **Hold.** Resolve citation sources, file-specific service/account provenance, and copied-material status. Preserve AI authorship disclosure. |

### OpenDota inquiry

Sent by Vitalii Babenko through [OpenDota Discord — help](https://discord.com/channels/144629812982448128/421587769664471069), the contact server linked from the official core README. Delivery was observed in the channel; no permission response has been recorded.

> I maintain a reproducible Dota 2 research repository. May I publicly redistribute frozen historical API-response snapshots, including match and player account IDs, with source attribution? My original code is MIT-licensed; third-party data would retain its applicable terms. Please identify the terms or permission covering this use, including any underlying Valve restrictions.

Record any reply with its source link, sender's authority, covered materials, conditions, and release decision before closing the checklist. Preserve original captures while clarification is pending.

## Identifiers

Match rows retain player account identifiers, match identifiers, timestamps, and team/roster links. These are pseudonymous, not anonymous. Roster identity depends on account sets; removing them changes reproducibility. Vitalii Babenko approves retaining player IDs for reproducibility, subject to source permission. Do not silently redact frozen evidence.

Local author/committer review found the owner's personal Gmail, work-domain email, and GitHub noreply identity. Vitalii Babenko chose to preserve history and explicitly allowed the work email to remain public after reviewing removal's impact. Rewriting identities changes affected commits and descendants; historical verification resolves manifest-bound original Git revisions, so deleting those objects would break that verification. A `.mailmap` or new Git identity changes presentation/future commits, not stored historical addresses. The configured identity for new commits uses the approved personal Gmail.

Keep API keys, credentials, private notes, and ignored stores out of publication. Scans cannot prove absence of secrets or establish rights. See the [publication scan](audits/2026-09-26-publication-scan.json), [advisory and hosting supplement](audits/2026-09-26-publication-supplement.json), and [release checklist](release-checklist.md) for coverage and unresolved dispositions.
