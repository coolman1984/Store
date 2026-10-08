# Store visual redesign contract — 2026-10-08

Source: Apps-Factory/design-factory/DESIGN.md (2026-10-08). Before implementation, inspect latest upstream and keep the contract synchronized.

## Brand
Provisional candidate **MIZAN | ميزان**; legal/trademark/domain review required before commercial use. Identity direction: balanced geometric shop mark, midnight navy, ivory and restrained copper; professional multi-branch retail operations. Do not rename shipped binaries or product until approved.

## Core problem
Current UI can pass technical tests yet feel visually inconsistent: weak hierarchy, tiny icons, irregular optical spacing, crowded cards and poor visual rhythm. The redesign must address composition, not just import existing CSS.

## Rollout
1. Capture actual before screenshots for dashboard, cashier, stock, sales, reports and settings on desktop/mobile, Arabic/English and dark/light.
2. Develop three coherent directions and pick one based on real cashier/store owner needs. Use factory typography/spacing/icon/button/component rules.
3. Build one approved design reference screen (dashboard and cashier); verify hierarchy, 20/24px icons, 44–48px controls, 4/8px spacing grid, 14–16px readable text and meaningful grouping.
4. Refactor shared shell, navigation, typography and components once; roll out to remaining views. Do not add new runtime frameworks or network dependencies.
5. Check keyboard, scanner, receipt, payment, returns, approvals, role restrictions, Arabic RTL, English LTR, offline behavior and mobile layouts after each slice.
6. Require before/after screenshots, visual human review, full test suite, 320/390/768/1440 widths, 200% zoom and accessibility checks before merging. Preserve append-only money/stock ledger.

## Acceptance
No tiny unlabeled icons, arbitrary gaps, cramped touch controls, overflow, clipped labels, fake metrics or inconsistent card alignment. Main action obvious on every screen. No regressions in the end-to-end sell/return/close shift journey. Missing evidence = UNVERIFIED, not PASS.

This commit is a specification only; visual implementation has not yet been completed or verified.
