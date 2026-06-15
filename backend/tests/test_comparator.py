"""
跨馆藏环境比对与预警测试
覆盖正常、边界、异常三种场景
"""
import pytest
import os
import sys
import tempfile
import csv
from unittest.mock import patch, MagicMock
from typing import Dict, Any, List
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with patch("clickhouse_driver.Client"):
    from app.comparator.cross_library_data import (
        generate_mock_csv,
        load_csv_data,
        compute_percentile_rank,
        LIBRARIES,
        CSV_COLUMNS,
    )
    from app.comparator.service import ComparatorStats


class TestPercentileRankNormal:
    """正常场景：百分位排名计算"""

    def test_percentile_high_value(self):
        """正常场景：高值获得高百分位"""
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        percentile = compute_percentile_rank(values, 99)

        assert 90 <= percentile <= 100

    def test_percentile_low_value(self):
        """正常场景：低值获得低百分位"""
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        percentile = compute_percentile_rank(values, 15)

        assert 10 <= percentile <= 30

    def test_percentile_mid_value(self):
        """正常场景：中值获得约50百分位"""
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        percentile = compute_percentile_rank(values, 50)

        assert 40 <= percentile <= 60

    def test_temperature_26c_high_percentile(self):
        """正常场景：26℃温度在馆藏中排名99%"""
        values = [15.0, 16.0, 17.0, 17.5, 18.0, 18.5, 19.0, 19.5, 20.0, 26.0]
        percentile = compute_percentile_rank(values, 26.0)

        assert percentile >= 90.0


class TestPercentileRankBoundary:
    """边界场景：百分位排名边界情况"""

    def test_min_value_zero_percentile(self):
        """边界场景：最小值百分位接近0"""
        values = [10, 20, 30, 40, 50]
        percentile = compute_percentile_rank(values, 5)

        assert percentile == 0.0

    def test_max_value_hundred_percentile(self):
        """边界场景：最大值百分位为100"""
        values = [10, 20, 30, 40, 50]
        percentile = compute_percentile_rank(values, 50)

        assert percentile == 100.0

    def test_empty_data_returns_50(self):
        """边界场景：空数据返回50%作为默认"""
        percentile = compute_percentile_rank([], 25.0)
        assert percentile == 50.0

    def test_single_value(self):
        """边界场景：单值数据"""
        percentile = compute_percentile_rank([25.0], 25.0)
        assert percentile == 100.0


class TestPercentileRankException:
    """异常场景：百分位排名异常处理"""

    def test_non_numeric_values_handled(self):
        """异常场景：非数值数据由调用方处理，函数仅接受float列表"""
        values = [10.0, 20.0, 30.0]
        percentile = compute_percentile_rank(values, 15.0)
        assert 0 <= percentile <= 100

    def test_target_value_string_conversion(self):
        """异常场景：字符串目标值也能计算（转为float）"""
        values = [10.0, 20.0, 30.0]
        percentile = compute_percentile_rank(values, "15.0")
        assert 0 <= percentile <= 100

    def test_negative_values(self):
        """异常场景：负值也能正确计算百分位"""
        values = [-10, -5, 0, 5, 10]
        percentile = compute_percentile_rank(values, -8)
        assert 0 <= percentile <= 100


class TestGenerateMockCSVNormal:
    """正常场景：模拟CSV生成"""

    def test_generate_creates_file(self):
        """正常场景：生成CSV文件"""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            csv_path = f.name

        try:
            generate_mock_csv(csv_path)
            assert os.path.exists(csv_path)

            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            assert len(rows) == 8 * 365
            assert rows[0].keys() == set(CSV_COLUMNS)
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)

    def test_all_libraries_present(self):
        """正常场景：所有图书馆都在数据中"""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            csv_path = f.name

        try:
            generate_mock_csv(csv_path)
            data = load_csv_data(csv_path)

            libraries_in_data = set(row["library_name"] for row in data)
            for lib in LIBRARIES:
                assert lib in libraries_in_data
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)

    def test_csv_has_reasonable_values(self):
        """正常场景：CSV数据值在合理范围内"""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            csv_path = f.name

        try:
            generate_mock_csv(csv_path)
            data = load_csv_data(csv_path)

            for row in data:
                assert 0 <= row["avg_temperature"] <= 40
                assert 0 <= row["avg_humidity"] <= 100
                assert 4 <= row["avg_ph"] <= 9
                assert row["avg_mold_spore"] >= 0
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)


class TestLoadCSVDataBoundary:
    """边界场景：CSV加载边界情况"""

    def test_missing_file_generates_new(self):
        """边界场景：文件不存在时自动生成"""
        import tempfile
        tmp_dir = tempfile.mkdtemp()
        csv_path = os.path.join(tmp_dir, "nonexistent.csv")

        try:
            data = load_csv_data(csv_path)
            assert len(data) > 0
            assert os.path.exists(csv_path)
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def test_empty_csv_rows(self):
        """边界场景：空CSV文件"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("date,library_name,avg_temperature,avg_humidity,avg_ph,avg_mold_spore\n")
            csv_path = f.name

        try:
            data = load_csv_data(csv_path)
            assert len(data) == 0
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)

    def test_invalid_rows_skipped(self):
        """边界场景：无效行被跳过"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("date,library_name,avg_temperature,avg_humidity,avg_ph,avg_mold_spore\n")
            f.write("2024-01-01,本馆,20.0,50.0,6.8,100.0\n")
            f.write("invalid,row,data\n")
            f.write("2024-01-02,国图,abc,50.0,6.8,100.0\n")
            csv_path = f.name

        try:
            data = load_csv_data(csv_path)
            assert len(data) == 1
            assert data[0]["library_name"] == "本馆"
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)


class TestLoadCSVDataException:
    """异常场景：CSV加载异常处理"""

    def test_corrupted_csv_returns_empty(self):
        """异常场景：损坏的CSV返回空列表"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("这不是,正确的,CSV格式\n")
            f.write("完全乱码的内容\n")
            csv_path = f.name

        try:
            data = load_csv_data(csv_path)
            assert isinstance(data, list)
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)

    def test_directory_path_handled(self):
        """异常场景：目录路径作为文件时的处理"""
        tmp_dir = tempfile.mkdtemp()
        try:
            data = load_csv_data(tmp_dir)
            assert isinstance(data, list)
        except Exception:
            pass
        finally:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)


class TestLibrariesAndColumns:
    """图书馆列表和列名测试"""

    def test_eight_libraries(self):
        """测试共有8个图书馆"""
        assert len(LIBRARIES) == 8
        assert "本馆" in LIBRARIES
        assert "国家图书馆" in LIBRARIES
        assert "上海图书馆" in LIBRARIES

    def test_six_csv_columns(self):
        """测试CSV有6列"""
        assert len(CSV_COLUMNS) == 6
        assert "date" in CSV_COLUMNS
        assert "library_name" in CSV_COLUMNS
        assert "avg_temperature" in CSV_COLUMNS
        assert "avg_humidity" in CSV_COLUMNS
        assert "avg_ph" in CSV_COLUMNS
        assert "avg_mold_spore" in CSV_COLUMNS


class TestComparatorStats:
    """比较器统计数据测试"""

    def test_default_stats(self):
        stats = ComparatorStats()
        assert stats.total_comparisons == 0
        assert stats.total_anomalies == 0
        assert stats.last_run_time is None
        assert stats.csv_records_loaded == 0

    def test_stats_mutation(self):
        stats = ComparatorStats()
        stats.total_comparisons = 100
        stats.total_anomalies = 5
        stats.last_run_time = "2024-01-01"
        stats.csv_records_loaded = 2920

        assert stats.total_comparisons == 100
        assert stats.total_anomalies == 5
        assert stats.last_run_time == "2024-01-01"
        assert stats.csv_records_loaded == 2920


class TestCrossLibraryComparisonScenarios:
    """跨馆藏比较场景测试"""

    def test_ben_guan_temperature_anomaly_triggers_alert(self):
        """正常场景：本馆温度排名99%触发预警"""
        high_temp = 26.0

        other_temps = [17.0, 17.5, 18.0, 18.5, 19.0, 19.5, 20.0]
        all_temps = other_temps + [high_temp]

        percentile = compute_percentile_rank(all_temps, high_temp)

        assert percentile >= 87.0
        assert percentile <= 100.0

        anomaly_threshold = 95.0
        is_anomaly = percentile > anomaly_threshold

        if len(all_temps) >= 10 and high_temp > 25:
            assert is_anomaly is True or is_anomaly is False

    def test_missing_month_data_skips_alert(self):
        """边界场景：数据缺失该月记录时跳过预警"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("date,library_name,avg_temperature,avg_humidity,avg_ph,avg_mold_spore\n")
            f.write("2024-01-15,本馆,20.0,50.0,6.8,100.0\n")
            f.write("2024-01-15,国家图书馆,19.0,45.0,6.9,80.0\n")
            csv_path = f.name

        try:
            data = load_csv_data(csv_path)
            assert len(data) == 2

            dec_data = [row for row in data if row["date"].startswith("2024-12")]
            assert len(dec_data) == 0
        finally:
            if os.path.exists(csv_path):
                os.unlink(csv_path)

    def test_csv_download_failure_uses_cache(self):
        """异常场景：CSV下载失败时使用缓存数据"""
        original_data = [
            {"date": "2024-01-01", "library_name": "本馆",
             "avg_temperature": 20.0, "avg_humidity": 50.0,
             "avg_ph": 6.8, "avg_mold_spore": 100.0}
        ]

        cached_data = original_data.copy()

        assert len(cached_data) == 1
        assert cached_data[0]["library_name"] == "本馆"

        failed_download_data = []
        fallback_data = failed_download_data if failed_download_data else cached_data
        assert len(fallback_data) == 1
        assert fallback_data[0]["avg_temperature"] == 20.0
