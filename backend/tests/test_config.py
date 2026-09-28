from app.config import Settings
from app.detection.detector import DetectorConfig


def test_template_settings_reach_the_detector_config() -> None:
    settings = Settings(template_mad_floor=2.0, max_templates=50, template_similarity=0.7)

    config = DetectorConfig.from_settings(settings)

    assert (config.template_mad_floor, config.max_templates, config.template_similarity) == (
        2.0,
        50,
        0.7,
    )
