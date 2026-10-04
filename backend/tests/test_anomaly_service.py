import pytest

from anomaly_service import detect_anomalies, screen_devices, train_calibration


def reference_lot():
    return [
        {
            "device_id": f"REF-{index}",
            "parameter": "iddq",
            "value_0h": 10 + index * 0.01,
            "value_24h": 10.2 + index * 0.01,
            "value_168h": 11.4 + index * 0.01,
        }
        for index in range(20)
    ]


def test_calibrated_lot_flags_a_sub_limit_outlier():
    calibration = train_calibration(reference_lot(), safety_slope=100)
    report = screen_devices(
        [
            {
                "device_id": "SUSPECT-1",
                "parameter": "iddq",
                "value_0h": 10.1,
                "value_24h": 45,
            }
        ],
        calibration,
        safety_slope=100,
    )

    device = report["devices"][0]
    assert device["flagged"] is True
    assert device["anomaly_flag"] is True
    assert device["explanations"][0]["robust_z_score"] > 3.5
    assert report["summary"]["flagged_devices"] == 1


def test_stable_device_passes_with_explainable_forecast():
    calibration = train_calibration(reference_lot(), safety_slope=0.05)
    report = screen_devices(
        [
            {
                "device_id": "GOOD-1",
                "parameter": "iddq",
                "value_0h": 10.08,
                "value_24h": 10.28,
            }
        ],
        calibration,
    )
    device = report["devices"][0]

    assert device["flagged"] is False
    assert device["prediction_168h"] == pytest.approx(11.48, abs=0.1)
    assert report["summary"]["health_percentage"] == 100
    assert report["forecast_method"] == "directional pinball-loss quantile regression"


def test_calibration_and_screening_reject_bad_inputs():
    with pytest.raises(ValueError, match="known-good"):
        screen_devices(
            [{"device_id": "A", "value_0h": 1, "value_24h": 2}],
            None,
        )
    with pytest.raises(ValueError, match="finite number"):
        train_calibration(
            [{"device_id": "A", "value_0h": float("nan")}]
        )
    with pytest.raises(ValueError, match="Duplicate device and parameter"):
        train_calibration(
            [
                {"device_id": "A", "value_0h": 1},
                {"device_id": "A", "value_0h": 2},
            ]
        )


def test_forecast_model_uses_asymmetric_directional_quantiles():
    references = [
        {
            "device_id": f"TRAIN-{index}",
            "parameter": "iddq",
            "value_0h": 1,
            "value_24h": 1,
            "value_168h": 10 + index / 10,
        }
        for index in range(10)
    ]
    high_calibration = train_calibration(references, direction="higher")
    low_calibration = train_calibration(references, direction="lower")

    high_prediction = screen_devices(
        [{"device_id": "H", "parameter": "iddq", "value_0h": 1, "value_24h": 1}],
        high_calibration,
    )["devices"][0]["prediction_168h"]
    low_prediction = screen_devices(
        [{"device_id": "L", "parameter": "iddq", "value_0h": 1, "value_24h": 1}],
        low_calibration,
    )["devices"][0]["prediction_168h"]

    assert high_calibration["parameters"]["iddq"]["forecast_model"]["quantile"] == 0.9
    assert low_calibration["parameters"]["iddq"]["forecast_model"]["quantile"] == 0.1
    assert high_prediction > 10.7
    assert low_prediction < 10.3


def test_legacy_single_series_detector_handles_outlier_and_constant_data():
    result = detect_anomalies([10, 10, 10, 10, 45], threshold=3)
    assert result["summary"]["anomaly_count"] == 1
    assert result["anomalies"][0]["value"] == 45
    assert detect_anomalies([2, 2, 2])["anomalies"] == []
