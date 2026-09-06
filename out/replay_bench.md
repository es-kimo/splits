# Replay benchmark

- 전체 리플레이(콜드): **10.308초** (목표: < 60초, 충족)
- 마지막 시즌 체크포인트 재개: **2.665초** (목표: < 5초, 충족)
- 최대 메모리: **172.99 MiB**
- 처리 경기: **18,847개**, 기간: **176개**

## 시즌별 처리 시간

| 시즌 | 처리 시간 |
| ---: | ---: |
| 2012 | 0.082초 |
| 2013 | 0.426초 |
| 2014 | 0.404초 |
| 2015 | 0.580초 |
| 2016 | 0.585초 |
| 2017 | 0.535초 |
| 2018 | 0.613초 |
| 2019 | 0.429초 |
| 2020 | 0.499초 |
| 2021 | 0.610초 |
| 2022 | 0.499초 |
| 2023 | 0.609초 |
| 2024 | 0.685초 |
| 2025 | 0.706초 |
| 2026 | 0.072초 |

## 프로파일 상위 항목

```text
100954727 function calls (99717564 primitive calls) in 24.356 seconds

   Ordered by: cumulative time
   List reduced from 475 to 15 due to restriction <15>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        1    0.149    0.149   24.725   24.725 rating/replay/orchestrator.py:163(replay)
      176    0.306    0.002   17.128    0.097 rating/engine/trueskill_wrapper.py:127(update)
    18846    0.291    0.000   16.178    0.001 <site-packages>/trueskill/__init__.py:433(rate)
    18846    0.526    0.000   15.176    0.001 rating/engine/trueskill_wrapper.py:25(run_schedule)
  1240234    1.396    0.000    6.022    0.000 <site-packages>/trueskill/factorgraph.py:160(update)
        1    0.020    0.020    5.541    5.541 rating/ledger/schema.py:326(validate_ledger)
   516342    0.623    0.000    4.913    0.000 <site-packages>/trueskill/factorgraph.py:189(up)
        1    0.856    0.856    4.540    4.540 rating/ledger/schema.py:140(build_pairwise_view)
  1411382    1.259    0.000    3.916    0.000 <site-packages>/trueskill/factorgraph.py:47(update_message)
   638378    0.559    0.000    3.805    0.000 <site-packages>/trueskill/factorgraph.py:144(up)
   601856    0.260    0.000    3.274    0.000 <site-packages>/trueskill/factorgraph.py:139(down)
       69    0.000    0.000    2.707    0.039 <site-packages>/polars/lazyframe/engine.py:415(collect)
       69    0.223    0.003    2.706    0.039 {method 'collect' of 'builtins.PyLazyFrame' objects}
       54    0.000    0.000    2.587    0.048 <site-packages>/polars/lazyframe/frame.py:2236(_collect_eager)
        3    0.000    0.000    2.484    0.828 <site-packages>/polars/dataframe/frame.py:10619(with_columns)
```
