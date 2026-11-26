.nr PS 11
.nr VS 15
.nr HM 0.65i
.nr FM 0.65i
.nr PO 0.7i
.nr LL 6.85i
.ds LH DEVFORGE / SECRET WARDS
.ds RH WARDPROOF
.ds CF %
.TL
WardProof
.AU
Team: Hard stuck-debugging
.br
Aditya S (lead), Mradul Verma, Moawya Mahmoud Shariff, Ayush Roy
.AI
Track 3: Secret Wards  |  github.com/aditya-zig/wardproof
.PP
.B "Share the clinical history, not the identity."
WardProof is an offline, CPU-only release pipeline for synthetic Indian hospital exports. Instead of copying documents and masking what it finds, it rebuilds outputs from recognized clinical fields, keeping supported doses, values and longitudinal intervals.
.NH 1
From raw export to release
.DS L
.ft CR
.ps 10
CSV / TSV / JSON / FHIR / notes
  |
  +--> Registry evidence in RAM --> Match or abstain --> HMAC patient ID
  |
  +--> Recognize schema --> Clinical allowlist --> Shift dates / rewrite IDs
             |                                   |
             +-- Unsupported: SHA-256 only       +-- sanitized/
                                                  +-- records.jsonl
                                                  +-- report.json
.ps
.ft
.DE
.NH 1
How it works
.IP "Ingestion" 15n
Reads supported CSV/TSV, JSON, clinical text and a single-patient FHIR R4 document subset. Recognizes UTF-8, UTF-16 BOMs and legacy registration text. Invalid or unfamiliar structures are reported by digest without an exported copy.
.IP "Detection" 15n
Structured paths, trusted headers and constrained value types form the allowlist. Text rules separate clinical phrases from relatives and retain supported medicines and doses. FHIR output rewrites references and omits attachments and original narrative.
.IP "Linkage" 15n
Latin and Devanagari names are compared by phonetic normalization. A shared phone and DOB plus a compatible name corroborate different hospital IDs. A full name and village must resolve to just one candidate for a name-only note; ambiguity returns no link. HMAC-SHA-256 pseudonyms are keyed by the injected secret.
.IP "What is different" 15n
The same Hindi prescription and Latin registration can link without linking a namesake, and one keyed date offset keeps a documented 9-day stay exactly 9 days.
.bp
.NH 1
Measured privacy versus utility
.PP
.B "Official synthetic practice kit, revision 6c0a85a."
179 of 200 files released; 21 quarantined. 771 ledger records, of which 694 have a pseudonym. On two logical CPUs with no network: about 0.14 seconds and 23 MiB peak RSS. The organizer contract validator passed; three repeat runs verified stability, key rotation, and no input changes.
.IP "Privacy" 15n
No personal data flags in the practice checker (0/3,230 across English, Hindi and Hinglish). No planted canaries in output (0/4) and no raw copies of unsupported files. These probes do not cover every possible leak.
.IP "Utility" 15n
3,585/4,753 checked medical values kept (75.4%). The denominator does not include all quarantined medical values. Linkage precision 1.00, recall 0.80, F0.5 0.95 on the practice checker, not an official hidden score.
.IP "Residual risk" 15n
We drop age and location and shift dates per patient, preserving intervals. In records with a diagnosis and shifted date in OPD/FHIR, 50/51 patients have at least one unique (shifted ISO week, diagnosis) pair. For FHIR stays, 16/19 patients have a unique (calendar-day stay length, diagnosis) pair. These proxies highlight potential singling-out; neither is the organizer's attack score.
.NH 1
Security design
.PP
No raw staging area or persistent identity index. Secrets arrive via an environment variable and are not written to the release. New files and directories use private modes; report and errors omit names, paths to raw inputs and raw content. Use an encrypted source and output volume; disk encryption is a deployment prerequisite, not implemented in the CLI. A quarantined file remains only in the original input, identified in the report by a digest.
.NH 1
What still fails
.PP
Unfamiliar formats and attachments are not interpreted. Clinical phrases outside the allowlist can be lost, including context or negation. Address-only or name-only records often abstain. Rare diagnoses, repeated visits and exact intervals may still identify people. An independently authored fixture with alternate headers, date formats and namesakes passed, but no hidden or blind corpus was scored. Synthetic competition data only.
"