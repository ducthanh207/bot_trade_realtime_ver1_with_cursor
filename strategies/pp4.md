---
disk: 1
id: "4"
name: PP4 — nâng cấp PP3
description: PP3 + Exit B thay early, hard stop % vốn, xác nhận RSI 1H, chặn RSI cực trị, ADX exhaustion; tuỳ chọn nhận diện giai đoạn + cắt lỗ sớm.
base: pp4
blocks:
  regime_cut: true
---
# PP4

- Toàn bộ khung PP3, cộng: chặn SHORT khi RSI < `M4_RSI_SHORT_FLOOR`, LONG khi RSI > `M4_RSI_LONG_CEIL`;
  cần RSI 1H cùng hướng (`M4_REQUIRE_1H_CONFIRM`); ADX quá cao thì giảm size (`M4_ADX_EXHAUSTION`).
- Hard stop mỗi lệnh `M4_MAX_STOP_CAPITAL_PCT` vốn; trailing 2.5 ATR 1H trong 12h đầu rồi 2.2.
- Khối `regime_cut` (docs/PP4_REGIME_EARLY_CUT.md): nhận diện giai đoạn và cắt lỗ sớm, **mặc định tắt**,
  bật bằng `M4_REGIME_ENABLED`, `M4_INVALIDATION_EXIT`, `M4_TIME_STOP`, `M4_SMOOTH_GRACE`.
