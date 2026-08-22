# RESEARCH_REJECTED

加权指数研究回测，不代表可成交合约或实盘收益

Run ID: `198adb3dfff347b497f0ca896102dcd7`

## Research domain

```json
{"candidate_threshold_pairs": 0, "embargo_bars": null, "feature_names": ["signed_kaufman_efficiency_20", "donchian_position_20", "momentum_acceleration_5_20", "intraday_intensity_10"], "horizon": null, "predictive": false, "selectable_models": [], "strategy_mode": "tianji", "thresholds": []}
```

## Run identity

`12550f5b327b167fcf5132358f0fe459410024c8e5370f476014761a09b5866a`

## Data exclusions

- AD_IDX: INCLUDED
- AG_IDX: INCLUDED
- AL_IDX: INCLUDED
- AO_IDX: INCLUDED
- AP_IDX: INCLUDED
- AU_IDX: INCLUDED
- A_IDX: INCLUDED
- BB_IDX: EXCLUDED ZERO_VOLUME_FRACTION
- BC_IDX: INCLUDED
- BR_IDX: INCLUDED
- BU_IDX: INCLUDED
- BZ_IDX: INCLUDED
- B_IDX: INCLUDED
- CF_IDX: INCLUDED
- CJ_IDX: INCLUDED
- CS_IDX: INCLUDED
- CU_IDX: INCLUDED
- CY_IDX: INCLUDED
- C_IDX: INCLUDED
- EB_IDX: INCLUDED
- EC_IDX: INCLUDED
- EG_IDX: INCLUDED
- FB_IDX: INCLUDED
- FG_IDX: INCLUDED
- FU_IDX: INCLUDED
- HC_IDX: INCLUDED
- IC_IDX: INCLUDED
- IF_IDX: INCLUDED
- IH_IDX: INCLUDED
- IM_IDX: INCLUDED
- I_IDX: INCLUDED
- JD_IDX: INCLUDED
- JM_IDX: INCLUDED
- J_IDX: INCLUDED
- L-F_IDX: INCLUDED
- LC_IDX: INCLUDED
- LG_IDX: INCLUDED
- LH_IDX: INCLUDED
- LU_IDX: INCLUDED
- L_IDX: INCLUDED
- MA_IDX: INCLUDED
- M_IDX: INCLUDED
- NI_IDX: INCLUDED
- NR_IDX: INCLUDED
- OI_IDX: INCLUDED
- OP_IDX: INCLUDED
- PB_IDX: INCLUDED
- PD_IDX: INCLUDED
- PF_IDX: INCLUDED
- PG_IDX: INCLUDED
- PK_IDX: INCLUDED
- PL_IDX: INCLUDED
- PP-F_IDX: INCLUDED
- PP_IDX: INCLUDED
- PR_IDX: INCLUDED
- PS_IDX: INCLUDED
- PT_IDX: INCLUDED
- PX_IDX: INCLUDED
- P_IDX: INCLUDED
- RB_IDX: INCLUDED
- RM_IDX: INCLUDED
- RR_IDX: INCLUDED
- RS_IDX: EXCLUDED ZERO_VOLUME_FRACTION
- RU_IDX: INCLUDED
- SA_IDX: INCLUDED
- SC_IDX: INCLUDED
- SF_IDX: INCLUDED
- SH_IDX: INCLUDED
- SI_IDX: INCLUDED
- SM_IDX: INCLUDED
- SN_IDX: INCLUDED
- SP_IDX: INCLUDED
- SR_IDX: INCLUDED
- SS_IDX: INCLUDED
- TA_IDX: INCLUDED
- TF_IDX: INCLUDED
- TL_IDX: INCLUDED
- TS_IDX: INCLUDED
- T_IDX: INCLUDED
- UR_IDX: INCLUDED
- V-F_IDX: INCLUDED
- V_IDX: INCLUDED
- WR_IDX: EXCLUDED ZERO_VOLUME_FRACTION
- Y_IDX: INCLUDED
- ZN_IDX: INCLUDED

## Split cutoffs

- holdout: `{"development_end": "2026-06-26T10:30:00", "development_start": "2025-10-16T09:15:00", "evaluation_end": "2026-08-13T23:15:00", "evaluation_start": "2026-06-26T10:45:00"}`

## Selected candidate

`null`

## Cost tables

- base/holdout/0 bp: return=-0.0763376632647037
- base/holdout/2 bp: return=-0.10208502081737336
- base/holdout/5 bp: return=-0.14070605714637774
- base/holdout/10 bp: return=-0.20507445102805233
- base/holdout/15 bp: return=-0.26944284490972703
- base/holdout/20 bp: return=-0.33381123879140095

## Per-symbol concentration

`null`

## Adversarial checks

- Not reached

## Gates

- integrity_checks: passed=True; reason=all TianJi integrity checks passed
- non_predictive_contract: passed=True; reason=no labels, fitting, prediction, or candidate selection
- payoff_ratio_5bps: passed=False; reason=payoff_ratio_5bps failed: observed=0.9008680872511822
- max_drawdown_5bps: passed=False; reason=max_drawdown_5bps failed: observed=0.14120242310086062
- minimum_trades_5bps: passed=True; reason=5 bp closed trade count passed
- positive_return_5bps: passed=False; reason=positive_return_5bps failed: observed=-0.14070605714637774
- cost_monotonicity: passed=True; reason=frozen TianJi trades decline with costs

## Pipeline counts

```json
{"failure_stage": "complete", "holdout_market_rows": 60171, "holdout_risk_ready_rows": 56131, "market_15m_rows": 382997, "risk_ready_rows": 299243, "signal_ready_rows": 230707, "target_rows": 812, "trade_rows_5bps": 683}
```

## Limitations

- 加权指数研究回测，不代表可成交合约或实盘收益
- 仅用于离线研究；不是可执行策略、合约仿真或实盘收益证据。
