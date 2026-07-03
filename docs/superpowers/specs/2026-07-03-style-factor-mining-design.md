# 风格因子挖掘(市值/估值/换手)+ 20日标签复验 — 设计

日期:2026-07-03 · 状态:用户已批准方向与方案
关联:`2026-06-27-quant-closed-loop-design.md`(闭环总设计)

## 背景与目标

现有 `FACTOR_LIBRARY` 34 个因子全部是量价层面(动量/波动/量能/日内/趋势),
挖出的 frozen composite 是短周期反转型。sqlite `daily_quotes`(415万行)里
**已有但从未参与挖掘**的字段:`turnover_rate / volume_ratio / circ_mv /
total_mv / pe / pb / amount`。

目标(用户拍板):
1. 用这些字段挖**市值/估值/换手/流动性**风格因子;
2. 现有+新因子在 **20日前向标签** 下复验一轮(看动量/趋势长周期是否翻正);
3. **只出报告不动生产线**——用户看完报告再决定是否重冻结上线;
4. 财务基本面(季度 fina_indicator)单独立项,不在本期。

## 方案(已选:路线A——扩展现有 qlib 管线)

一处改动打通全链:CSV 导出层加字段 → qlib bin 自动带上(vendored
DumpDataAll 默认导出 CSV 全部列)→ 因子表达式直接引用 `$pe` 等 → 挖掘/
去重/合成/回测全部复用现有代码。

弃选路线B(pandas 直挖 sqlite):会产生第二套挖掘代码,长期双维护。

## 组件与改动

### ① 数据层 `app/backtest/qlib_data.py` + `scripts/build_qlib_data.py`
- 新函数 `export_market_csvs_full(session, codes, start, end, out_dir)`:
  直接查 `DailyQuote` 全字段(绕过 `DailyBar`,不动它——它被全站引用),
  CSV 列:date/open/high/low/close/volume/factor + **turnover_rate/
  volume_ratio/circ_mv/total_mv/pe/pb/amount**。
- 估值/换手/市值字段**不复权**(本来就不该复权);null 保留为空由 qlib
  读成 NaN,表达式层天然跳过;PE 可为负,保留原值。
- `build_qlib_data.py` 切换到新导出函数。指数 CSV(SH000300)不加字段,
  dump_bin 对缺列符号自动只写有的列(冒烟时验证,若不行则给指数补空列)。
- 风险:CSV/bin 体积增大(7列→14列,约翻倍);每晚 step_qlib 重导时间
  变长——冒烟时测量,如超时可接受性差再谈优化(YAGNI)。

### ② 因子库 `app/quant/factor_mine.py` FACTOR_LIBRARY 新增约15个
市值:`ln_mv`=Log($circ_mv+1)、`mv_chg20`=$circ_mv/Ref($circ_mv,20)-1
估值:`ep`=1/$pe(PE负→EP负,天然有序)、`bp`=1/$pb
     (时序分位类估值因子不做,YAGNI,先只用截面原值)
换手:`turn5`=Mean($turnover_rate,5)、`turn20`=Mean($turnover_rate,20)、
     `turn_chg5_20`=Mean($turnover_rate,5)/(Mean($turnover_rate,20)+1e-12)、
     `turn_std20`=Std($turnover_rate,20)/(Mean($turnover_rate,20)+1e-12)
流动性:`amihud_amt20`=Mean(Abs($close/Ref($close,1)-1)/($amount+1),20)
       (真实成交额版,替代现有 volume*close 近似)、
       `amt5_20`=Mean($amount,5)/(Mean($amount,20)+1)
量比:`vr5`=Mean($volume_ratio,5)、`vr_chg`=$volume_ratio/(Mean($volume_ratio,20)+1e-12)
市值中性化交叉项不做(交给相关性去重+等权合成)。
最终名单以实现时表达式引擎可用算子为准,±3个浮动。

### ③ 挖掘运行(复用 run_factor_mining.py,不改逻辑只跑两轮)
- 轮1:`--horizon 5`(与现有34因子同窗直接对比)
- 轮2:`--horizon 20`(长周期复验,重点看 mom/slope/sharpe 是否翻正)
- IS/OOS 分割沿用 `--split 2025-01-01`;稳健门槛沿用 |IC|≥0.02、|IR|≥0.3
- 产出:`data/reports/factor_mining_<asof>_h5.{json,md}`、`..._h20.{json,md}`
  (文件名带 horizon 后缀,避免覆盖 6-11 报告;run_factor_mining.py 加
  `--suffix` 或按 horizon 自动命名——实现时定,倾向自动)

### ④ 对比回测(复用 run_composite_backtest.py)
新报告(h5)跑一次复合因子回测,与 6-17 现有 composite 回测对比:
RankIC/IR/分层收益/最大回撤。产出 markdown 里给"新旧对比"小节。

### ⑤ 明确不做
- 不改 frozen_composite.json、不动 22:00 生产链、不改辩论提示词
- 不做财务基本面(下期)、不做分钟级/研报因子(数据不足)
- 不做因子市值中性化、行业中性化(等有行业数据再说)

## 数据流

sqlite daily_quotes(全字段)
 → export_market_csvs_full → data/qlib_csv/*.csv(14列)
 → DumpDataAll → data/qlib_cn/*.bin
 → run_factor_mining --horizon {5,20}(FACTOR_LIBRARY 34+15)
 → data/reports/factor_mining_*_h{5,20}.{json,md}
 → run_composite_backtest(h5 报告)→ 新旧对比
 → 用户审阅 → (另行决定)freeze_factors 重冻结

## 错误处理
- pe/pb/turnover_rate 早期日期可能缺失 → NaN,factor_report 的 dropna
  已处理;若某因子有效样本过少(<30%天数),报告标注并不入稳健名单。
- 指数符号缺新列 → dump 或表达式报错时给指数 CSV 补 NaN 列。
- 挖掘跑在 nice 15 下,避免抢占网页服务(4核机)。

## 测试
- 单元:export_market_csvs_full 列名/不复权/None→空值(内存 sqlite);
  新因子表达式冒烟(qlib D.features 在 --limit 300 小池上能算出非全NaN)。
- 集成:--smoke 全链(小池短窗)出报告;检查 h5/h20 两份文件都生成。
- 现有 342 个测试不回归。

## 验收
1. 两份挖掘报告落地,含新因子的 IS/OOS RankIC 与稳健名单;
2. h5 新旧复合因子回测对比小节;
3. 生产线行为零变化(当晚 22:00 正常跑旧 frozen);
4. 全量测试通过。
