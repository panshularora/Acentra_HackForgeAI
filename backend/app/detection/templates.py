"""Group log lines into templates with Drain3 and pull out their parameters.

Drain3 (He et al., "Drain: An Online Log Parsing Approach with Fixed Depth
Tree", ICWS 2017) learns templates online: lines with the same shape, such as
``ERROR claim-adjudication msg="DB connection timeout" req=<*> ... ip=<IP>``,
land in the same cluster, and the tokens that vary between them become
parameters. Counting errors per template instead of in one global total lets
a new failure stand out even when it is a small share of all traffic.

The miner only ever sees masked lines: the parser masks PHI before this
module runs, so neither template text nor parameters can carry a member ID,
name or date of birth.

Tuning:

* The timestamp is dropped before mining, and the tree depth is set so the
  level and service are the first two tokens Drain3 routes on. Lines from
  different services or levels therefore never share a template.
* IPv4 addresses are masked by Drain3 as ``<IP>`` so every line of a
  credential-stuffing burst from one address still yields the address as a
  parameter, even though it never varies within the template.
* ``max_templates`` caps Drain3's cluster cache (least recently used clusters
  are evicted), bounding memory under a flood of unique lines.
"""

import logging
from dataclasses import dataclass

from drain3 import TemplateMiner  # type: ignore[import-untyped]
from drain3.masking import MaskingInstruction  # type: ignore[import-untyped]
from drain3.template_miner_config import TemplateMinerConfig  # type: ignore[import-untyped]

# Root, token count, level and service: level and service each get a tree layer.
DRAIN_DEPTH = 5
IPV4 = r"((?<=[^A-Za-z0-9])|^)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})((?=[^A-Za-z0-9])|$)"
# Parameter names are taken from ``key=value`` tokens; these keys all mean the client address.
PARAM_ALIASES = {"ip": "source_ip", "client_ip": "source_ip"}

# Drain3 logs every new cluster at INFO, which would drown the service log.
logging.getLogger("drain3").setLevel(logging.WARNING)


@dataclass(frozen=True, slots=True)
class TemplateMatch:
    """The template a line belongs to, and the parameter values it carried."""

    id: str
    text: str
    params: tuple[tuple[str, str], ...]


class TemplateCatalog:
    """Online Drain3 template miner over masked log lines."""

    def __init__(self, max_templates: int, similarity: float) -> None:
        config = TemplateMinerConfig()
        config.drain_depth = DRAIN_DEPTH
        config.drain_sim_th = similarity
        config.drain_max_clusters = max_templates
        config.masking_instructions = [MaskingInstruction(IPV4, "IP")]
        config.profiling_enabled = False
        self._miner = TemplateMiner(config=config)

    @property
    def count(self) -> int:
        """Distinct templates created so far (including any evicted from the cache)."""
        return int(self._miner.drain.clusters_counter)

    def match(self, masked_line: str) -> TemplateMatch:
        """Add ``masked_line`` to the miner and return its template and parameters."""
        content = line_content(masked_line)
        result = self._miner.add_log_message(content)
        text = str(result["template_mined"])
        extracted = self._miner.extract_parameters(text, content, exact_matching=False) or []
        names = _placeholder_names(text)
        params = tuple(
            _named(name, param.value) for name, param in zip(names, extracted, strict=False)
        )
        return TemplateMatch(id=str(result["cluster_id"]), text=text, params=params)

    def text(self, template_id: str) -> str | None:
        """Current text of a template (it generalises as more lines arrive)."""
        cluster = self._miner.drain.id_to_cluster.get(int(template_id))
        return None if cluster is None else str(cluster.get_template())


def line_content(masked_line: str) -> str:
    """The part of a log line that is mined: everything after the leading timestamp."""
    parts = masked_line.split(maxsplit=1)
    return parts[1] if len(parts) == 2 else masked_line


def _placeholder_names(template: str) -> list[str | None]:
    """For each placeholder in ``template``, the key it belongs to if it is ``key=<...>``."""
    names: list[str | None] = []
    for token in template.split():
        if "<*>" not in token and "<IP>" not in token:
            continue
        key, sep, _ = token.partition("=")
        names.append(key if sep and not key.startswith("<") else None)
    return names


def _named(name: str | None, value: str) -> tuple[str, str]:
    """Name a parameter value, splitting ``key=value`` when the whole token varied."""
    if name is None:
        key, sep, rest = value.partition("=")
        name, value = (key, rest) if sep and key.isidentifier() else ("param", value)
    return PARAM_ALIASES.get(name, name), value.strip('"')
