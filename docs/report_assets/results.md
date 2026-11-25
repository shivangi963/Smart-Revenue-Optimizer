# Results tables (auto-generated)

Model version **v20261003.1342**, trained on 25,000 synthetic observations (20,000 train / 5,000 test). MAE/RMSE in INR; revenue/profit lift vs static base-price pricing.

## Model comparison

| Strategy | MAE | RMSE | R² | Revenue lift | Profit lift | Latency (ms) |
|---|---:|---:|---:|---:|---:|---:|
| Static pricing | 153.19 | 333.52 | -0.293 | +0.00% | +0.0% | 0.00 |
| Rule-based | 119.98 | 256.88 | 0.192 | +1.70% | +6.0% | 0.29 |
| Linear Regression | 29.75 | 62.14 | 0.943 | +4.50% | +23.5% | 1.55 |
| Random Forest | 49.11 | 95.50 | 0.822 | +4.26% | +21.5% | 7.13 |
| Gradient Boosting | 22.93 | 45.52 | 0.966 | +4.59% | +23.5% | 1.52 |
| Oracle (upper bound) | 17.08 | 34.88 | 0.985 | +4.64% | +23.9% | 0.00 |

Gradient Boosting captures **99%** of the revenue lift attainable by a perfect oracle.

## Feature importance by group (Gradient Boosting)

| Group | Importance |
|---|---:|
| Demand | 38.0% |
| Events & Holidays | 21.6% |
| Weather | 19.4% |
| Stock Level | 9.1% |
| Time & Season | 6.9% |
| Competition | 4.8% |
| Product | 0.3% |

## Top individual features

| Feature | Importance |
|---|---:|
| traffic_index | 22.6% |
| stock_ratio | 8.9% |
| event_score | 8.3% |
| temp_x_icecream | 7.9% |
| urgency_x_ticket | 7.6% |
| conversion_rate | 7.0% |
| add_to_cart_rate | 5.9% |
| cold_x_hotbev | 5.7% |
| rain_x_umbrella | 4.8% |
| competitor_ratio | 4.8% |

## Demand model

- R² vs true expected demand: **0.994**
- Mean absolute error: 0.57 units/hour
- Revenue-maximising price located within **4.8%** of the true optimum (of base price)

## Feature table

| Group | Features |
|---|---|
| Time & Season | hour_of_day, hour_sin, hour_cos, day_of_week, is_weekend, month, month_sin, month_cos, monsoon_x_umbrella, summer_x_icecream, winter_x_hotbev |
| Demand | page_views_1h, traffic_index, add_to_cart_rate, conversion_rate |
| Stock Level | stock_ratio, low_stock_flag |
| Weather | temperature, precipitation, humidity, is_rainy, is_hot, rain_x_umbrella, temp_x_icecream, cold_x_hotbev |
| Events & Holidays | is_holiday, event_score, days_to_event, event_proximity, urgency_x_ticket |
| Competition | competitor_ratio |
| Product | cost_ratio, cat_umbrella, cat_ice_cream, cat_ticket, cat_hot_beverage, cat_generic |