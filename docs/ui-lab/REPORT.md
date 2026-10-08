# UI Lab report — 2026-10-08T13:37

Base: http://127.0.0.1:8197 · CPU throttle ×4 · budgets: ui-budgets/1 (2026-10-08)

| Page | Screen | FCP | LCP | CLS | TBT | INP | p95 frame | FPS | DOM | JS kB | Fits | a11y | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| home | 1366x768 | 396 | 984 | 0.001 | 75 | 0 | 33.4 | 45.6 | 348 | 46 | ✓ | 0 | PASS |
| pos | 1366x768 | 396 | 396 | 0.001 | 22 | 0 | 16.7 | 59.5 | 356 | 52 | ✓ | 0 | PASS |
| sales | 1366x768 | 348 | 348 | 0.001 | 0 | 0 | 16.7 | 60 | 219 | 44 | ✓ | 0 | PASS |
| customers | 1366x768 | 368 | 804 | 0.001 | 0 | 0 | 16.7 | 60 | 200 | 48 | ✓ | 0 | PASS |
| products | 1366x768 | 412 | 412 | 0.001 | 84 | 0 | 16.8 | 60 | 225 | 43 | ✓ | 0 | PASS |
| stock | 1366x768 | 468 | 468 | 0.001 | 69 | 0 | 33.3 | 56 | 717 | 47 | ✓ | 0 | PASS |
| cash | 1366x768 | 380 | 872 | 0.001 | 10 | 0 | 33.4 | 45.9 | 224 | 43 | ✓ | 0 | PASS |
| watch | 1366x768 | 412 | 900 | 0.001 | 0 | 0 | 16.8 | 60 | 195 | 50 | ✓ | 0 | PASS |
| reports | 1366x768 | 448 | 1036 | 0.001 | 105 | 0 | 33.4 | 43.8 | 565 | 49 | ✓ | 0 | PASS |
| help | 1366x768 | 424 | 424 | 0.001 | 0 | 0 | 16.7 | 60 | 325 | 48 | ✓ | 0 | PASS |
| home | 390x844 | 376 | 836 | 0 | 113 | 0 | 16.7 | 60 | 348 | 46 | ✓ | 0 | PASS |
| pos | 390x844 | 396 | 832 | 0 | 9 | 0 | 16.8 | 60 | 356 | 53 | ✓ | 0 | PASS |
| sales | 390x844 | 344 | 344 | 0 | 0 | 0 | 16.7 | 60 | 219 | 44 | ✓ | 0 | PASS |
| customers | 390x844 | 388 | 676 | 0 | 0 | 0 | 16.7 | 60 | 200 | 48 | ✓ | 0 | PASS |
| products | 390x844 | 384 | 2236 | 0 | 22 | 0 | 16.7 | 60 | 225 | 47 | ✓ | 0 | PASS |
| stock | 390x844 | 380 | 724 | 0 | 42 | 0 | 16.8 | 58.5 | 717 | 52 | ✓ | 0 | PASS |
| cash | 390x844 | 324 | 676 | 0 | 26 | 0 | 16.7 | 60 | 224 | 43 | ✓ | 0 | PASS |
| watch | 390x844 | 348 | 588 | 0 | 0 | 0 | 16.7 | 60.5 | 195 | 48 | ✓ | 0 | PASS |
| reports | 390x844 | 344 | 728 | 0 | 75 | 0 | 16.7 | 60 | 565 | 46 | ✓ | 0 | PASS |
| help | 390x844 | 352 | 352 | 0 | 0 | 0 | 16.8 | 60 | 325 | 48 | ✓ | 0 | PASS |

Largest JS transfer of one page: 53 kB (budget 300 kB).

## Accessibility findings

- home 1366x768: region(moderate,2)
- pos 1366x768: region(moderate,2)
- sales 1366x768: landmark-unique(moderate,1), region(moderate,2)
- customers 1366x768: landmark-unique(moderate,1), region(moderate,2)
- products 1366x768: region(moderate,2)
- stock 1366x768: landmark-unique(moderate,1), region(moderate,2)
- cash 1366x768: landmark-unique(moderate,1), region(moderate,2)
- watch 1366x768: region(moderate,2)
- reports 1366x768: region(moderate,2)
- help 1366x768: region(moderate,2)
- home 390x844: region(moderate,1)
- pos 390x844: region(moderate,1)
- sales 390x844: region(moderate,1)
- customers 390x844: region(moderate,1)
- products 390x844: region(moderate,1)
- stock 390x844: region(moderate,1)
- cash 390x844: region(moderate,1)
- watch 390x844: region(moderate,1)
- reports 390x844: region(moderate,1)
- help 390x844: region(moderate,1)
