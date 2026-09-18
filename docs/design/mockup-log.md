# Nightkeep prototype mockups: design log

Canvas: **Nightkeep Prototype Screens** (Claude Design), private, owned by the team.
https://claude.ai/artifact/Gye9zkkioeiLxXLUgiMbMw

Team CodeRed · MUSA CodeX 2026 · Cyber Security · CX0204 "Ransom at the Ration Shop"
Log covers versions 1 to 13, built 17 to 18 September 2026. Recorded here in full
on 18 September 2026 so the console ticket does not depend on anyone re-opening
the canvas to find these decisions.

This is the source-of-truth record for the console's copy, layout and data
shape. See ADR-0005 for how it changes `mock_pds` and CLAUDE.md.

---

## 1. What the canvas is for

The mockups are the reference the console gets built against. They are not
decoration and not the pitch deck. They exist to answer one question a judge
will ask in Round 2: *can a person who works at a ration counter actually use
this during an attack?*

Everything else about the project (architecture, research, threat model, demo
video, the full write-up) belongs on the deployed project website. The canvas
is deliberately narrow.

---

## 2. Final contents: 7 artboards

### Group 1: the ration card system the office uses

| File | Title | Size | What it shows |
|---|---|---|---|
| `Main.dc.html` | Ration card search | 1280 x 876 | Search form (card number, head of family, taluka, FPS, scheme, status), 5 result rows, district figures, a Data Safety panel |
| `PdsCard.dc.html` | Ration card detail | 1280 x 956 | One card: household details, 4 members with e-KYC status, monthly entitlement, ePoS collection history |
| `PdsLocked.dc.html` | The same screen during the attack | 1280 x 796 | "Ration card records cannot be opened", empty result table, the simulator's ransom note, what the office does next |

### Group 2: Data Safety, written for the counter clerk

| File | Title | Size | What it shows |
|---|---|---|---|
| `NkHome.dc.html` | Data Safety, everything is fine | 1280 x 1044 | "Your records are safe", copy counts, the six night tasks with Usually / Last night, one marked "Later than usual" |
| `NkAlert.dc.html` | Data Safety, attack report | 1280 x 996 | "Someone tried to lock your files. It was stopped.", four figures, five-step timeline, What to do now |
| `NkRestore.dc.html` | Get my records back | 1280 x 926 | Three steps, five plain-language verification checks, the loss window, PIN entry |
| `ServerAlert.dc.html` | Pop-up on the office computer | 600 x 380 | The only Nightkeep surface that appears on the PDS server |

Canvas note pinned beside the pop-up: *only this pop-up appears on the office
computer; the Data Safety screens run on a separate machine that nothing on
the network can reach.*

---

## 3. Design system as it now stands

| Token | Value | Rule |
|---|---|---|
| Typeface | Noto Sans, with Noto Sans Devanagari for the Marathi line | One family. Weight carries hierarchy, not size jumps |
| Type scale | 11.5 utility, 12 caption, 12.5 table and secondary, 13.5 body, 15 lead, 18 page heading, 25 status headline | Seven sizes, no others |
| Primary | `#14387f` navy | The system colour |
| Active tab | `#b0451a` orange | Marks the active nav tab and nothing else |
| Safe | `#1a6b3c` green | Real state only |
| Needs review | `#8a5200` amber | Real state only |
| Incident | `#9b2226` red | Real state only |
| Body text | `#17202b`, secondary `#3a4655` | Both pass WCAG AA on white |
| Borders | `#c2cddb` at 1px | Every block, no exceptions |
| Corner radius | 0 | Square everywhere, the way government sites are |
| Page gutter | 20px | Utility strip, header, breadcrumb, content and nav all start here |
| Block inner gutter | 10px | Headers, table cells and body text inside a block share this |
| Control height | 44px | Inputs and buttons match, so form rows sit on one baseline |
| Numbers | `font-variant-numeric: tabular-nums` | Columns line up |
| Em-dashes | Zero | Checked mechanically in every file |

Government chrome kept on every screen: blue utility strip with Skip to main
content, screen reader link, text resize and English/मराठी; saffron-white-green
hairline; district seal placeholder; bilingual office name; navy nav with one
orange tab; breadcrumb; page heading.

---

## 4. Change history and the reason for each change

### v1 to v2, the first build (6 boards)

Built the Nightkeep console only, in GIGW house style: dashboard with three
status lights labelled HABIT / RANSOM / RECOVERY, a verdict feed table, Habit
Cards with learned ranges next to the hidden ground-truth log, a Vault
snapshot page with the manifest hash chain, a Restore Wizard, and the server
pop-up.

Decision taken at the start: use the government visual language but label the
office generically, with a `[DEPT SEAL]` placeholder instead of the Ashoka
emblem and no real department name. A mockup that imitates a real government
body is a different thing from a mockup that looks governmental, and only the
second one is safe to show and share.

### v3, rebuilt in two groups (10 boards)

**Why:** the screens read as a security tool, not as something a PDS office
would operate. Two problems. First, a judge had no way to see what was
actually at stake, because the ration card data never appeared. Second, the
console spoke in entropy, habit scores and snapshots, which a District Supply
Officer does not.

**Changes:**
- Added five screens of the PDS application itself: portal home, ration card
  search, card detail, monthly allocation, and the portal during the attack.
  This is the thing that gets ransomed, and seeing it working first makes the
  attack land.
- Rewrote the Nightkeep screens in counter-clerk language. "Your data is
  safe" instead of three coloured lights. "37 files damaged" instead of an S3
  signal. Night tasks named by what they do rather than by filename.
- Moved every technical view behind "For the IT person" links. Nothing was
  deleted, only demoted.
- Added the deep-modules architecture section to the Claude Code kickoff
  prompt, with the rule that `HabitScore`, `Verdict` and `RestoreResult`
  carry their plain-language reasons, built inside the module that knows why.
  The console renders those strings and never re-derives them. That single
  decision is what lets the UI stay simple.

### v4, real data and an anti-slop pass (trimmed to 7 boards)

**Why:** two separate problems. The data conventions were invented, which a
judge from a government background would spot immediately. And the design
had accumulated the marks of generated work.

**Data changes, each checked against a source:**

| Before | After | Source |
|---|---|---|
| `RC-104872` | `110300512847`, a 12-digit number with no prefix | Maharashtra ration card numbers are 12 digits |
| `FPS-014` | `27030300145` plus a shop name | AePDS shop IDs are numeric |
| "Priority Household (PHH)" as a loose label | `NFSA-PHH`, `AAY`, `Kesari (APL)` | NFSA scheme names |
| "Rice 20 kg, Wheat 12 kg, Sugar 1 kg" for 4 members | Rice 12.000 kg + wheat 8.000 kg, stated as 5 kg per member | NFSA: 5 kg per person per month for Priority Household, issued in Maharashtra as 3 kg rice and 2 kg wheat. AAY is 35 kg per card regardless of family size |
| No price shown | "Free under PMGKAY" | PMGKAY extended five years from 1 January 2024, so free grain is correct for September 2026. The older ₹3 and ₹2 NFSA rates would be wrong |
| Plain collection rows | ePoS transactions with an authentication mode (Biometric / OTP) | How ePoS records actually read |
| Aadhaar absent or vague | "Aadhaar seeded: 3 of 4 members", never a number | No Aadhaar-format number is generated anywhere |
| Real-sounding district | Kesargaon, invented, talukas Kesargaon and Nandori | So it cannot be mistaken for a real office |
| Generic names | Marathi names with a middle name, e.g. Sunita Ramesh Kadam | Matches how the field is filled in practice |

**Design changes:**
- One corner radius: square. One accent: navy, with orange reserved for the
  active nav tab. Three semantic colours used only where there is real state.
- Dropped the second typeface so there is one family.
- Removed every em-dash and every decorative separator dot.
- Removed decorative status circles and the invented visitor counter.
- Table numbers switched to tabular figures.

**Screens cut:** portal home, monthly allocation, and the separate
night-tasks page. Search, card detail and the attacked state carry the PDS
story on their own, and the night-tasks register folded into the Data Safety
status page as a section. Ten boards to seven.

### v6, action steps moved to the top, then v8, reverted

A comment asked for the three instructions to be the first thing on the
attack report. They were merged with the red headline into one panel at the
top, and the duplicate block at the bottom was removed.

**Then reverted** on the follow-up comment: position was fine, only emphasis
was wanted. The page went back to headline, figures, timeline, What to do
now. The steps stayed where they were and got a heavier border, a larger
section header, solid navy numbered squares and a taller button.

Worth recording because it is a real design lesson: *the most important thing
on a page does not have to be the highest thing on the page.* On this screen
the person needs the facts before the instruction makes sense.

### v10, step 1 highlighted in place

"Do not restart the office computer" now sits on a light red band with a 5px
red bar down the left edge, a red number square and bold dark red text. Steps
2 and 3 are unchanged.

A short line was added under it: *"Restarting can wipe the evidence and can
let the locking program start again."* A clerk's first instinct on a broken
machine is to reboot, and the instruction holds better when it says why.

### v11, alignment fixes

Four real defects, found after a comment that elements looked misaligned:

1. **Nav bar gutter.** The navy menu started 28px from the left while the
   utility strip, header, breadcrumb and content all started at 20px.
   Container padding went from 12px to 4px so the first item's text lands at
   20px.
2. **Border weights.** The red headline had a 2px edge, tables 1px, the
   action panel 3px, so their left edges stepped in and out down the column.
   Everything is 1px now; emphasis comes from the coloured header band
   instead.
3. **Inner gutters.** Text started at 22px in the headline block, 10px in
   tables and 15px in the timeline. All unified to 10px.
4. **Step rhythm.** Steps 2 and 3 carried different padding from step 1, so
   the gaps between the three were unequal.

Also made both label columns in the summary table the same width, and
applied the nav and gutter fixes to all seven boards so the set stays
consistent.

### v12, footer removed

The navy footer bar with the prototype disclaimer was removed from all six
full screens, and each board shortened by 36px so the space did not sit
empty.

Nothing was lost: the "Prototype on invented data. Not a live government
system" line still runs along the top strip of every screen.

### v13, polish pass

- **Page headings.** Every screen now has a real `<h1>` in a white band under
  the breadcrumb. There was not a single heading element anywhere before,
  which is both an accessibility gap and why screens felt like they started
  mid-thought.
- **Control heights.** Inputs were 38px and buttons 44px, so in the search
  form the Search button sat lower than the fields beside it. Both are 44px
  and buttons centre their label properly rather than relying on padding.
- **Link-buttons.** "Open Data Safety" and "Get my records back" each
  carried their own hand-written padding. They now use the shared button
  styles.
- **Type scale.** Twelve sizes down to seven.
- **Banner parity.** The green "Your records are safe" and red "Someone
  tried to lock your files" banners are identical in size, line height and
  padding, so flipping between the calm and attacked states reads as one
  screen changing rather than two different designs.
- **Night tasks rewritten.** The worst-reading block. Rows were run-on
  sentences: *"Normally: Between 01:04 and 02:27, writing About 240 new
  files."* They are now label-and-value pairs with aligned columns, Usually
  and Last night, so the eye can scan six tasks and land on the one marked
  "Later than usual".

---

## 5. Points to note before building

**The numbers are placeholders.** 5,000 records, 37 files damaged of 12,480,
six-second detection, 19 counter entries, 24 safe copies, the Day 9 01:20
clean point. Every one comes from the MVP targets, not from a run. MVP.md
section 11 says all numbers on slides after 22 September must come from real
runs. Replace these once F1 and F2 produce output, and replace them in the
mockups too so the design and the demo never disagree on stage.

**MVP.md and the kickoff prompt currently contradict each other on card
IDs.** MVP.md section 4 reads as still specifying `RC-` style IDs at a glance;
in fact it already carries an inline note, "superseded by ADR-0003", pointing
at the 12-digit format these mockups use. No further fix needed there.

**One conventions file.** The kickoff prompt asks for `mock_pds/conventions.py`
holding the card number format, FPS ID format, scheme names and entitlement
rules, so the data generator and the Jinja templates read the same constants.
Skipping it is how the search screen ends up showing a format the detail
screen does not.

**The console must not listen on the network.** MVP.md section 8 records
that an earlier design let office PCs open the console as a web page, and
that this was a door the team built itself. The design was changed so the
console exists only on the Vault's own screen. Bind Flask to `127.0.0.1`.
The pop-up is the only Nightkeep surface on the PDS server, which is exactly
what `ServerAlert.dc.html` is.

**Plain language is a requirement, not a preference.** On the main path, no
entropy, SHA-256, habit score, MAD, manifest, snapshot or verdict. Night
tasks by what they do, not by filename. Everything technical behind a "For
the IT person" link. This is what makes the console defensible when a judge
asks who operates it.

**The disclaimer must survive.** Every screen carries "Prototype on invented
data. Not a live government system." in the top strip, the district is
invented, and no Aadhaar-format number exists anywhere. Keep all three in the
built console. See ADR-0005.

**One open question.** The saffron-white-green hairline under the top bar is
still in place. It was kept because it is a genuine convention on Indian
government sites and is doing real work in selling the look. If it should go,
it is one line per file.

**What is deliberately not here.** No monthly allocation screen, no portal
home, no separate habit-card browser, no snapshot timeline page, no evidence
bundle view. They were cut to keep the demo tight. If a judge asks to see
them, that is what the deployed project site is for.

---

## 6. Version reference

| Version | Change |
|---|---|
| 1 to 2 | First build, 6 boards, Nightkeep console only |
| 3 | Rebuilt as 10 boards in two groups, PDS app added, plain language adopted |
| 4 | Trimmed to 7 boards, real data conventions, anti-slop pass |
| 6 | Action steps moved to top of the attack report |
| 8 | Reverted, steps emphasised in place instead |
| 10 | Step 1 highlighted in red, reason line added |
| 11 | Nav gutter, border weights, inner gutters, step rhythm, table widths |
| 12 | Footer bar removed, board heights trimmed |
| 13 | Page headings, 44px controls, type scale, banner parity, night tasks rewritten |

---

## 7. Fields the mockups use that were not yet in the tracker

Read against `docs/adr/0003-ration-card-numbers.md` and the ticket #2 data
conventions, six fields appear in `Main.dc.html` and `PdsCard.dc.html` that
were never part of the sourced-data pass in v4's table above: card status
(Active / Suspended), card type, address, village (separate from taluka),
card issue date, and ePoS transaction status (Collected / Part collected).
ADR-0005 folds these into the conventions and into ticket #2.
