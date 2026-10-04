from __future__ import annotations

import math
from statistics import median
from typing import Any

READING_FIELDS = ("value_0h", "value_24h", "value_96h", "value_168h")
ANOMALY_SCORE_LIMIT = 3.5
MIN_REFERENCES_PER_PARAMETER = 5


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be a finite number.") from error
    if not math.isfinite(result):
        raise ValueError(f"{field} must be a finite number.")
    return result


def normalize_records(records: Any, *, require_pair: bool) -> list[dict[str, Any]]:
    if not isinstance(records, list) or not records:
        raise ValueError("Provide a non-empty list of device records.")

    normalized: list[dict[str, Any]] = []
    identifiers: set[tuple[str, str]] = set()
    for row_number, raw in enumerate(records, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"Record {row_number} must be an object.")
        device_id = str(raw.get("device_id", "")).strip()
        parameter = str(raw.get("parameter") or "leakage_current").strip()
        if not device_id or not parameter:
            raise ValueError(f"Record {row_number} needs device_id and parameter.")
        identifier = (device_id, parameter)
        if identifier in identifiers:
            raise ValueError(f"Duplicate device and parameter: {device_id} / {parameter}.")
        identifiers.add(identifier)

        record: dict[str, Any] = {
            "device_id": device_id,
            "parameter": parameter,
            "lot_id": str(raw.get("lot_id", "")).strip(),
        }
        for field in READING_FIELDS:
            if raw.get(field) not in (None, ""):
                record[field] = _number(raw[field], f"Record {row_number} {field}")
        if require_pair and not all(field in record for field in ("value_0h", "value_24h")):
            raise ValueError(f"Record {row_number} needs value_0h and value_24h.")
        if not any(field in record for field in READING_FIELDS):
            raise ValueError(f"Record {row_number} needs at least one numeric reading.")
        normalized.append(record)
    return normalized


def _robust_scale(values: list[float], center: float) -> float:
    mad = median([abs(value - center) for value in values])
    if mad > 0:
        return 1.4826 * mad
    q1, q3 = _quantile(values, 0.25), _quantile(values, 0.75)
    iqr_scale = (q3 - q1) / 1.349
    if iqr_scale > 0:
        return iqr_scale
    return max(abs(center) * 1e-6, 1e-9)


def _quantile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _predict_value_168(record: dict[str, Any]) -> float:
    value_0h = record["value_0h"]
    value_24h = record["value_24h"]
    return value_24h + (value_24h - value_0h) * 6


def _fit_directional_quantile_model(
    rows: list[dict[str, Any]], direction: str
) -> dict[str, Any] | None:
    training_rows = [
        row for row in rows if all(field in row for field in ("value_0h", "value_24h", "value_168h"))
    ]
    if len(training_rows) < 10:
        return None

    features = [
        [row["value_0h"], row["value_24h"] - row["value_0h"]]
        for row in training_rows
    ]
    targets = [row["value_168h"] for row in training_rows]
    feature_means = [sum(row[column] for row in features) / len(features) for column in range(2)]
    feature_scales = [
        math.sqrt(sum((row[column] - feature_means[column]) ** 2 for row in features) / len(features))
        or 1.0
        for column in range(2)
    ]
    target_mean = sum(targets) / len(targets)
    target_scale = math.sqrt(
        sum((value - target_mean) ** 2 for value in targets) / len(targets)
    ) or 1.0
    normalized_features = [
        [
            (row[column] - feature_means[column]) / feature_scales[column]
            for column in range(2)
        ]
        for row in features
    ]
    normalized_targets = [(value - target_mean) / target_scale for value in targets]

    quantile = 0.90 if direction == "higher" else 0.10
    intercept = _quantile(normalized_targets, quantile)
    coefficients = [0.0, 0.0]
    learning_rate = 0.035
    for _ in range(1800):
        intercept_gradient = 0.0
        coefficient_gradients = [0.0, 0.0]
        for row, target in zip(normalized_features, normalized_targets):
            residual = target - intercept - sum(
                coefficient * feature for coefficient, feature in zip(coefficients, row)
            )
            if residual > 1e-10:
                prediction_gradient = -quantile
            elif residual < -1e-10:
                prediction_gradient = 1 - quantile
            else:
                prediction_gradient = 0.0
            intercept_gradient += prediction_gradient
            for index, feature in enumerate(row):
                coefficient_gradients[index] += prediction_gradient * feature
        count = len(training_rows)
        intercept -= learning_rate * intercept_gradient / count
        for index, gradient in enumerate(coefficient_gradients):
            coefficients[index] -= learning_rate * (
                gradient / count + 1e-5 * coefficients[index]
            )

    return {
        "quantile": quantile,
        "feature_means": feature_means,
        "feature_scales": feature_scales,
        "target_mean": target_mean,
        "target_scale": target_scale,
        "intercept": intercept,
        "coefficients": coefficients,
        "training_count": len(training_rows),
    }


def _predict_from_model(record: dict[str, Any], model: dict[str, Any]) -> float:
    features = [
        record["value_0h"],
        record["value_24h"] - record["value_0h"],
    ]
    normalized = [
        (value - model["feature_means"][index]) / model["feature_scales"][index]
        for index, value in enumerate(features)
    ]
    prediction = model["intercept"] + sum(
        coefficient * value
        for coefficient, value in zip(model["coefficients"], normalized)
    )
    return model["target_mean"] + model["target_scale"] * prediction


def train_calibration(
    records: Any,
    *,
    safety_slope: float | None = None,
    direction: str = "higher",
) -> dict[str, Any]:
    reference = normalize_records(records, require_pair=False)
    if direction not in ("higher", "lower"):
        raise ValueError("direction must be 'higher' or 'lower'.")
    if safety_slope is not None:
        safety_slope = _number(safety_slope, "safety_slope")
        if safety_slope <= 0:
            raise ValueError("safety_slope must be greater than zero.")

    by_parameter: dict[str, list[dict[str, Any]]] = {}
    for row in reference:
        by_parameter.setdefault(row["parameter"], []).append(row)

    parameters: dict[str, Any] = {}
    for name, rows in by_parameter.items():
        if len(rows) < MIN_REFERENCES_PER_PARAMETER:
            raise ValueError(
                f"Parameter '{name}' needs at least {MIN_REFERENCES_PER_PARAMETER} "
                "known-good reference records."
            )
        feature_stats: dict[str, Any] = {}
        for field in READING_FIELDS:
            samples = [row[field] for row in rows if field in row]
            if len(samples) >= MIN_REFERENCES_PER_PARAMETER:
                center = median(samples)
                feature_stats[field] = {
                    "median": center,
                    "scale": _robust_scale(samples, center),
                    "count": len(samples),
                }
        for required_field in READING_FIELDS[:2]:
            if required_field not in feature_stats:
                raise ValueError(
                    f"Parameter '{name}' needs at least {MIN_REFERENCES_PER_PARAMETER} "
                    f"known-good '{required_field}' readings."
                )

        residuals: list[float] = []
        slopes: list[float] = []
        for row in rows:
            if all(field in row for field in READING_FIELDS[:2]):
                slopes.append(
                    (row["value_24h"] - row["value_0h"]) / 24
                    * (1 if direction == "higher" else -1)
                )
            if all(field in row for field in ("value_0h", "value_24h", "value_168h")):
                projected = _predict_value_168(row)
                signed_error = (row["value_168h"] - projected) * (
                    1 if direction == "higher" else -1
                )
                residuals.append(signed_error)

        safe_slope = safety_slope
        if safe_slope is None:
            safe_slope = max(
                _quantile(slopes, 0.95) if slopes else 0.0,
                1e-9,
            )
        # A 90th percentile one-sided residual margin makes forecasts cautious
        # about under-prediction while remaining calibrated to this good lot.
        forecast_margin = max(0.0, _quantile(residuals, 0.90)) if residuals else 0.0
        parameters[name] = {
            "features": feature_stats,
            "safety_slope": safe_slope,
            "forecast_margin": forecast_margin,
            "forecast_model": _fit_directional_quantile_model(rows, direction),
            "reference_count": len(rows),
        }

    return {
        "parameters": parameters,
        "device_count": len({row["device_id"] for row in reference}),
        "measurement_count": len(reference),
        "direction": direction,
        "anomaly_score_limit": ANOMALY_SCORE_LIMIT,
    }


def _score_against_baseline(
    record: dict[str, Any], baseline: dict[str, Any]
) -> tuple[float, list[dict[str, Any]]]:
    features = baseline["features"]
    explanations: list[dict[str, Any]] = []
    for field in READING_FIELDS:
        if field not in record or field not in features:
            continue
        stats = features[field]
        delta = record[field] - stats["median"]
        z_score = 0.6745 * delta / stats["scale"]
        explanations.append(
            {
                "feature": field,
                "value": record[field],
                "baseline_median": stats["median"],
                "robust_z_score": z_score,
                "shap_value": z_score**2,
                "contribution": abs(z_score),
                "direction": "above" if delta > 0 else "below" if delta < 0 else "at",
            }
        )
    if not explanations:
        raise ValueError(
            f"No matching calibrated readings for parameter '{record['parameter']}'."
        )
    score = math.sqrt(sum(item["shap_value"] for item in explanations))
    explanations.sort(key=lambda item: item["contribution"], reverse=True)
    return score, explanations


def screen_devices(
    records: Any,
    calibration: dict[str, Any] | None,
    *,
    safety_slope: float | None = None,
) -> dict[str, Any]:
    if not calibration or not calibration.get("parameters"):
        raise ValueError("Calibrate a known-good reference lot before screening.")
    devices = normalize_records(records, require_pair=True)
    if safety_slope is not None:
        safety_slope = _number(safety_slope, "safety_slope")
        if safety_slope <= 0:
            raise ValueError("safety_slope must be greater than zero.")

    direction = calibration["direction"]
    results: list[dict[str, Any]] = []
    for row in devices:
        baseline = calibration["parameters"].get(row["parameter"])
        if baseline is None:
            raise ValueError(
                f"Parameter '{row['parameter']}' has no matching reference calibration."
            )
        anomaly_score, explanations = _score_against_baseline(row, baseline)
        forecast_model = baseline["forecast_model"]
        if forecast_model:
            predicted_168h = _predict_from_model(row, forecast_model)
        else:
            predicted_168h = _predict_value_168(row) + (
                baseline["forecast_margin"] * (1 if direction == "higher" else -1)
            )
        drift_per_hour = (predicted_168h - row["value_0h"]) / 168
        worsening_slope = drift_per_hour * (1 if direction == "higher" else -1)
        applicable_slope = safety_slope or baseline["safety_slope"]
        anomaly_flag = anomaly_score >= ANOMALY_SCORE_LIMIT
        slope_flag = worsening_slope > applicable_slope
        reasons: list[str] = []
        if anomaly_flag:
            top_feature = explanations[0]
            reasons.append(
                f"{top_feature['feature']} is {top_feature['direction']} the "
                f"reference-lot median ({top_feature['robust_z_score']:.1f} robust z-score)."
            )
        if slope_flag:
            reasons.append(
                f"Forecast drift {worsening_slope:.6g}/h exceeds the "
                f"safety slope {applicable_slope:.6g}/h."
            )
        results.append(
            {
                **row,
                "prediction_168h": predicted_168h,
                "forecast_method": (
                    "directional pinball-loss quantile regression"
                    if forecast_model
                    else "conservative linear extrapolation"
                ),
                "predicted_drift_per_hour": drift_per_hour,
                "safety_slope": applicable_slope,
                "anomaly_score": anomaly_score,
                "anomaly_flag": anomaly_flag,
                "slope_flag": slope_flag,
                "flagged": anomaly_flag or slope_flag,
                "risk": "high" if anomaly_flag or slope_flag else "normal",
                "explanations": explanations,
                "reason": " ".join(reasons) if reasons else "No calibrated anomaly or safety-slope limit exceeded.",
            }
        )

    device_flags: dict[str, bool] = {}
    for result in results:
        device_id = result["device_id"]
        device_flags[device_id] = result["flagged"] or device_flags.get(device_id, False)
    flagged_devices = sum(device_flags.values())
    device_count = len(device_flags)
    forecast_methods = {
        "directional pinball-loss quantile regression"
        if baseline["forecast_model"]
        else "conservative linear extrapolation"
        for baseline in calibration["parameters"].values()
    }
    return {
        "devices": results,
        "summary": {
            "total_devices": device_count,
            "flagged_devices": flagged_devices,
            "healthy_devices": device_count - flagged_devices,
            "health_percentage": round(
                100 * (device_count - flagged_devices) / device_count, 2
            ),
        },
        "forecast_method": next(iter(forecast_methods)) if len(forecast_methods) == 1 else "mixed forecast methods",
        "explainability_method": "exact additive Shapley values for the robust-distance score",
    }


def detect_anomalies(values: Any, threshold: float = 3.0) -> dict[str, Any]:
    """Compatibility endpoint using robust scores for a single uncalibrated series."""
    data = [_number(value, "value") for value in values]
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("threshold must be a finite number greater than zero.")
    if not data:
        return {
            "values": [],
            "anomalies": [],
            "summary": {
                "count": 0,
                "mean": 0.0,
                "std_dev": 0.0,
                "threshold": threshold,
                "anomaly_count": 0,
            },
        }

    center = median(data)
    scale = _robust_scale(data, center)
    scores = [0.6745 * (value - center) / scale for value in data]
    anomalies = [
        {"index": index, "value": value, "z_score": abs(score)}
        for index, (value, score) in enumerate(zip(data, scores))
        if abs(score) > threshold
    ]
    average = sum(data) / len(data)
    variance = sum((value - average) ** 2 for value in data) / len(data)
    return {
        "values": data,
        "anomalies": anomalies,
        "summary": {
            "count": len(data),
            "mean": average,
            "std_dev": math.sqrt(variance),
            "threshold": threshold,
            "anomaly_count": len(anomalies),
            "method": "median and median absolute deviation",
        },
    }
