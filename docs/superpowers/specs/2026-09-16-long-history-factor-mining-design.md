# 长历史多周期因子重检 + 财务/资金流新家族扩库 设计

**日期**:2026-09-16
**状态**:已实施(2026-09-16):研究库+regime 重检+新家族+合成升级+财务续接落地,候选 A(23 因子 IR 加权)已上生产 frozen

## 背景与动机

2026-09-15 tushare 到期前完成了历史全量落库:`ashare.db` 日线 2010-01-04 起无缺天(含已退市股,无幸存者偏差),`data/tushare_extra.db` 有 2010 起的季频四表(fina_indicator 108 列 / income / balancesheet / cashflow)、每日个股资金流(1400 万行)、分红表、指数日线与成分权重。

现有生产因子(创业板 h20 低风险异象 27 因子等权)存在三个已知短板:

1. **只在一段行情里验证过**:IS 2022~2024 / OOS 2025 起,qlib 库只有 2021 年起数据。27 个因子几乎全是"低波动/低换手/低流动/反彩票"一族,互相高度相关,强依赖当前小盘反转 regime,长历史里是否稳健完全未知。
2. **信号来源单一**:全部是量价派生,财务质量/成长、资金流、分红这三块信息现在一点没进因子库。
3. **合成粗糙**:等权、只按 |corr|<0.8 贪心去重,`composite_score` 忽略 `weights` 字段;同族因子堆叠等于给一族信息加了十几倍权重。

## 目标

1. 用 2010 年起的长历史,把现有 48 个因子按 7 个 regime 逐段检验,标出"只在某段行情有效"的因子。
2. 新增财务质量/成长、资金流、分红三个家族约 20 个因子,按公告日做 point-in-time 对齐,零未来信息。
3. 合成升级:按族去相关 + 按 OOS IC-IR 加权,通过验证闸与同窗回测后决定是否替换 frozen。

## 非目标

- 不改交易执行层(门槛/仓位/退出)。
- 不改夜链 `data/qlib_cn`(仍 2021 起)的重建流程;研究库独立。
- 不上 LightGBM;不做行业中性化(创业板宇宙行业分布本身偏科技,留后续)。
- 资金流因子**只做研究**:tushare 到期后无免费同口径续接源,即使有效也不进 frozen(见"数据续接"节)。

## 总体架构

```
ashare.db (2010+) ──┐
                    ├─ scripts/build_qlib_data.py --research ──► data/qlib_cn_full/   (研究库,2010 起,含新字段)
tushare_extra.db ───┘        │                                        │
                             │ app/quant/pit_fields.py                 │ instruments/cyb_dyn.txt(按日动态)
                             ▼                                        ▼
                  scripts/run_factor_regimes.py ──► data/reports/factor_regimes_<date>_h20.{json,md}   (第 1 步)
                  scripts/run_factor_mining.py --qlib-dir research ──► factor_mining_<date>_h20_full   (第 2 步)
                  scripts/freeze_factors.py(族去相关+IR 加权)──► frozen_composite.json                 (第 3 步)
                  scripts/validate_frozen_alignment.py + run_composite_backtest.py 同窗对比
```

`Settings` 新增 `qlib_research_dir: str = "./data/qlib_cn_full"`。研究脚本通过 `--research` 或 `--qlib-dir` 指向它;生产 `qlib_provider` 继续用 `qlib_data_dir`。

## 第 0 步:研究库与动态宇宙

### 0.1 研究库导出

`scripts/build_qlib_data.py` 加参数:`--start 2010-01-01`(覆盖 `qlib_export_start`)、`--qlib-dir`/`--csv-dir` 已有、`--extra`(附加 PIT 字段)。研究库固定命令:

```
python scripts/build_qlib_data.py --start 2010-01-01 --csv-dir data/qlib_csv_full --qlib-dir data/qlib_cn_full --extra
```

预计:2021 起全导 9 分钟,2010 起约 30~40 分钟,bin 约 2 GB;手动/按需重建,不进夜链。

### 0.2 PIT 附加字段(`app/quant/pit_fields.py`)

从 `tushare_extra.db` 生成每只票每日一行的附加列,再 merge 进该票 CSV。对齐规则:**交易日 d 可用的财报 = `ann_date <= d` 的所有报告里 `ann_date` 最新的一份**(同一 ann_date 多份取 `end_date` 最新);向前填充,发布前为 NaN。fina_indicator 里同 (code,end_date) 有多条(重述),按 ann_date 各自生效,自动满足 PIT。

季频派生(先按 end_date 排序、去重后再做):

| 字段 | 定义 | 来源 |
|---|---|---|
| `np_ttm` | 归母净利 TTM(元):单季 = 本期 ytd − 上期 ytd(Q1 即本身),TTM = 最近 4 个单季和 | income.n_income_attr_p |
| `rev_ttm` | 营收 TTM | income.revenue |
| `ocf_ttm` | 经营现金流 TTM | cashflow.n_cashflow_act |
| `sue` | 单季净利同比差 /(最近 8 季该差的 std):(q_t − q_{t−4}) / std | income 单季序列 |
| `q_roe` | 单季 ROE(%) | fina_indicator.q_roe |
| `gm` | 毛利率(%) | fina_indicator.grossprofit_margin |
| `q_sales_yoy` / `q_profit_yoy` | 单季营收/净利同比(%) | fina_indicator |
| `profit_acc` | q_profit_yoy − 上一季 q_profit_yoy(增速加速度) | 派生 |
| `accrual` | (n_income_attr_p − n_cashflow_act) / total_assets,ytd 口径 | income + cashflow + balancesheet |
| `debt_to_assets` | 资产负债率(%) | fina_indicator |
| `total_assets` | 总资产(元) | balancesheet |
| `dps_ttm` | 过去 365 天内 `ex_date <= d` 的 `cash_div_tax` 之和(元/股,div_proc='实施') | dividend |
| `ann_age` | d 距最近一次财报公告日的交易日数(公告当日=0) | 派生 |

日频资金流(按 trade_date 直接对齐,单位万元):`mf_lg_net` = (buy_lg+buy_elg) − (sell_lg+sell_elg) 的 amount;`mf_sm_net` = buy_sm − sell_sm;`mf_net` = net_mf_amount。

单元测试:公告日之前必须 NaN;重述按新 ann_date 生效;TTM 跨年(Q1 单季=ytd)正确;dps 窗口边界;缺表/缺票不抛错整列 NaN。

### 0.3 动态宇宙 `cyb_dyn`

qlib instruments 文件天然支持每行 `SYMBOL\tSTART\tEND`。新增 `app/quant/universe.py::dynamic_rows(basic_rows, *, min_list_days, cal_start, cal_end)`:对每只 300/301 开头的票,start = max(list_date + 120 自然日, cal_start),end = delist_date−1 或 cal_end;仍按当前名称剔 ST(已知局限,沿用)。`scripts/build_universe.py --dynamic --name cyb_dyn --qlib-dir data/qlib_cn_full`,基础信息来自 `tushare_extra.db.ts_stock_basic`(含 339 只已退市),baostock 兜底。同法可出 `investable_dyn`(全市场)备用。

## 第 1 步:多 regime 重检(`scripts/run_factor_regimes.py`)

- 输入:研究库 + `cyb_dyn` + 现有 `FACTOR_LIBRARY`(48)+ 第 2 步新增因子(同一脚本,一次跑完)。起点 2011-01-04(创业板此时 ≥150 只),label = h20。
- 计算:`D.features` 一次取全(float32,创业板约 1340 只 × 3800 日 ≈ 5M 行,内存 <3 GB),按 `factor_report` 逐日 RankIC,聚合到:
  - 逐年(2011..2026)
  - 7 个 regime:R1 2011-01~2014-06 震荡熊 / R2 2014-07~2015-06 杠杆牛 / R3 2015-07~2016-02 股灾 / R4 2016-03~2018-12 白马去杠杆 / R5 2019-01~2021-12 成长牛 / R6 2022-01~2024-08 小盘红利熊 / R7 2024-09~今 924 后
- 每因子指标:各 regime RankIC 均值与 IR、同号 regime 数、`min_abs_ic`、全期 IR、近三年 IR。**全周期稳健**判定:≥6/7 个 regime 与全期同号,且 ≥5 个 regime |RankIC|≥0.015。同时输出"当前 frozen 27 个"逐个的判定表。
- 产出 `data/reports/factor_regimes_<date>_h20.{json,md}`;md 里每族一节,用 +/−/0 标注各 regime 方向,便于肉眼看 regime 依赖。
- 这一步结果先给用户看,再进第 2/3 步。

## 第 2 步:新家族扩库(`app/quant/factor_mine.py`)

新增两个字典并合入 `FACTOR_LIBRARY`(用 qlib 表达式,基于 0.2 字段;`$total_mv`/`$circ_mv` 单位万元):

**FUNDAMENTAL_FACTORS(研究库有字段才可算)**

- 估值:`ep_ttm` = `$np_ttm/($total_mv*1e4+1)`;`sp_ttm` = `$rev_ttm/($total_mv*1e4+1)`;`cfp_ttm` = `$ocf_ttm/($total_mv*1e4+1)`;`dy` = `$dps_ttm/($close+1e-12)`
- 质量:`q_roe`;`gm`;`gm_chg` = `$gm-Ref($gm,250)`(约一年前,forward-fill 后近似);`accrual`(预期反向);`ocf_np` = `$ocf_ttm/(Abs($np_ttm)+1)`;`lev` = `$debt_to_assets`
- 成长:`q_sales_yoy`;`q_profit_yoy`;`profit_acc`;`sue`;`asset_g` = `$total_assets/(Ref($total_assets,250)+1)-1`(预期反向,资产增长异象)
- 事件:`pead` = `If(Le($ann_age,20),$sue,0)`(公告后 20 个交易日内的 SUE,否则 0;盈余公告后漂移)

**FLOW_FACTORS(研究专用,不进 frozen)**

- `lg_net5` = `Mean($mf_lg_net,5)/(Mean($amount,5)*0.1+1)`(amount 千元→万元);`lg_net20`;`sm_net5` 同法;`lg_net_chg` = `lg_net5 − lg_net20`;`mf_cons20` = `Mean(Greater($mf_lg_net,0),20)`(大单净流入天数占比)

`NOVEL` 集合扩展;`run_factor_mining.py` 加 `--qlib-dir`,缺字段的因子自动跳过并在报告标注。IS/OOS 双窗改为长窗:IS 2011~2021(或 `--is-start`),OOS 2022~今,与第 1 步 regime 表交叉看。

## 第 3 步:合成升级

1. `composite_score(panel, signs, weights=None)`:有 weights 时做加权均值(权重归一);无则等权(向后兼容,现有测试不变)。`qlib_provider.score_panel` 传 `frozen.weights`。
2. `FACTOR_FAMILY: dict[name -> family]`(动量/反转/波动/量能/量价相关/价位/日内/趋势/流动性/分布/极值/市值/估值/换手/质量/成长/分红/资金流)。`select_frozen` 新参数 `family_cap=2`、`threshold=0.7`:按 |IR| 降序贪心,同族最多留 2 个且与已留因子 |corr|<0.7。
3. 权重 = 各因子 OOS IR 绝对值归一(截断在 [0.5×均值, 2×均值] 防单因子独大),写进 `weights`。
4. 候选池 = 第 1 步"全周期稳健" ∩ 第 2 步"双窗稳健"。
5. 验收:`validate_frozen_alignment.py` PASS(OOS RankIC ≥ 0.05 且分层单调),并用 `run_composite_backtest.py` 在**同一窗口**跑旧 frozen(27 等权)vs 新 frozen,比较年化/回撤/IR/换手。新组合在回撤或 IR 上没有改善则**不替换**,只留报告。
6. 替换时旧产物自动归档(`save_frozen` 已有);新 frozen 若含财务因子,夜链 `data/qlib_cn` 也必须带这些字段(见下)。

## 数据续接(财务因子进生产的前提)

- tushare 财报到 2026-06-30 报告期为止。财务因子若进 frozen,需要 `scripts/update_financials_baostock.py`:用 baostock `query_profit_data / query_growth_data / query_balance_data / query_cash_flow_data` 按季追加到 `tushare_extra.db` 的一张 `fin_pit` 汇总表(只存 0.2 所需列 + ann_date),夜链 qlib 导出(`export_market_csvs_full`)顺带 merge 该表。这一项**在第 3 步决定采用财务因子后再做**,本 spec 只预留:0.2 的 `pit_fields.py` 读的是统一列名视图,不绑定 tushare 表结构。
- 资金流无免费续接 → 研究专用。

## 错误处理

- PIT 生成:某票某表缺失 → 该票该列全 NaN,不抛错;日志计数缺失票数。
- `D.features` 缺字段(在夜链库跑到财务因子)→ 挖掘脚本捕获并跳过该因子,报告里标 `skipped: missing field`。
- 研究库导出中途失败可重跑(CSV 幂等覆盖)。

## 测试

- `tests/test_pit_fields.py`:PIT 无前视、TTM、SUE、dps 窗口、重述生效、缺表容错。
- `tests/test_universe_dynamic.py`:动态起止日、退市截止、次新剔除。
- `tests/test_factor_regimes.py`:regime 切分与聚合、稳健判定(用合成小面板)。
- `tests/test_factor_compose.py` 扩展:加权合成、族上限去重、权重截断。
- 现有 408 测试全绿。

## 交付顺序与检查点

1. 第 0 步 + 第 1 步 → 给用户看 regime 报告(检查点 1)。
2. 第 2 步 → 长窗挖掘报告。
3. 第 3 步 → 同窗对比 + 验证闸,用户拍板是否替换 frozen(检查点 2)。
