import os
import logging
from bisect import bisect_left
from typing import List, Optional, Tuple, Union
from datetime import datetime
from pathlib import Path
import numpy as np
from _textsearch import row_ids_to_row_splits as _row_ids_to_row_splits

Pathlike = Union[str, Path]

PUCTUATIONS = {
    "all": set("'.;?!():-<>/\"。；？！（）：-《》【】”“"),
    "eos": set(".?,，!。？！"),
    "left": set("\"'(<《【“"),
    "right": set("\"')>》】”"),
}


class AttributeDict(dict):
    def __getattr__(self, key):
        if key in self:
            return self[key]
        raise AttributeError(f"No such attribute '{key}'")

    def __setattr__(self, key, value):
        self[key] = value

    def __delattr__(self, key):
        if key in self:
            del self[key]
            return
        raise AttributeError(f"No such attribute '{key}'")


def setup_logger(
    log_filename: Pathlike,
    log_level: str = "info",
    dist: Optional[Tuple[int, int]] = None,
    use_console: bool = True,
) -> None:
    """Setup log level.

    Args:
      log_filename:
        The filename to save the log.
      log_level:
        The log level to use, e.g., "debug", "info", "warning", "error",
        "critical"
      use_console:
        True to also print logs to console.
    """
    now = datetime.now()
    date_time = now.strftime("%Y-%m-%d-%H-%M-%S")
    if dist is not None:
        rank, world_size = dist
        formatter = f"%(asctime)s %(levelname)s [%(filename)s:%(lineno)d] ({rank}/{world_size}) %(message)s"  # noqa
        log_filename = f"{log_filename}-{date_time}-{rank}"
    else:
        formatter = (
            "%(asctime)s %(levelname)s [%(filename)s:%(lineno)d] %(message)s"
        )
        log_filename = f"{log_filename}-{date_time}"

    os.makedirs(os.path.dirname(log_filename), exist_ok=True)

    level = logging.ERROR
    if log_level == "debug":
        level = logging.DEBUG
    elif log_level == "info":
        level = logging.INFO
    elif log_level == "warning":
        level = logging.WARNING
    elif log_level == "critical":
        level = logging.CRITICAL

    logging.basicConfig(
        filename=log_filename,
        format=formatter,
        level=level,
        filemode="w",
    )
    if use_console:
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(logging.Formatter(formatter))
        logging.getLogger("").addHandler(console)


def row_ids_to_row_splits(row_ids: np.ndarray) -> np.ndarray:
    """Convert row ids to row splits.

    Args:
      row_ids:
        A 1-D array of dtype np.uint32 containing row ids.
    Returns:
      Return a 1-D array of dtype np.uint32 containing row splits.
    """
    assert row_ids.ndim == 1, row_ids.ndim
    assert row_ids.dtype == np.uint32, row_ids.dtype

    row_ids = np.ascontiguousarray(row_ids)
    num_rows = row_ids[-1] + 1
    row_splits = np.empty(num_rows + 1, dtype=np.uint32)

    _row_ids_to_row_splits(row_ids, row_splits)
    return row_splits


def is_overlap(
    ranges: List[Tuple[float, float]],
    indexes: List[int],
    query: Tuple[float, float],
    segment_index: int,
    overlap_ratio: float = 0.25,
) -> Tuple[bool, Union[int, None]]:
    """
    Return True if the given range overlaps with the existing ranges.

    Caution:
      `ranges` and `indexes` will be modified in this function.

    Note: overlapping here means the length of overlapping area is greater than
    some threshold (currently, the threshold is `overlap_ratio` multiply the length
    of the query or existing ranges).

    Args:
      ranges:
        The existing ranges, it is sorted in ascending order on input, and we will
        keep it sorted in this function.
      indexes:
        The index (into the selected segments) of each range belongs to.
      query:
        The given range.
      segment_index:
        The index (into the selected segments) of query to be inserted.
      overlap_ratio:
        The ratio of overlapping part to the query or existing segments. If the
        ratio is greater than `overlap_ratio` we will drop the query or existing
        segment.

    Return:
      Return (False, None) if no overlapping between query and existing ranges.
      Return (True, None) if the ratio of overlapping part to query is greater
      than `overlap_ratio`.
      Return (True, dindex) if the ratio of overlapping part to existing range
      is greater than `overlap_ratio`, `dindex` is the index (can get from indexes)
      of the existing range.
    """
    index = bisect_left(ranges, query)
    if not ranges:
        ranges.insert(index, query)
        indexes.insert(index, segment_index)
        return False, None

    # overlapping on query
    if index > 0:
        is_overlap = (
            ranges[index - 1][1] - query[0]
            > (query[1] - query[0]) * overlap_ratio
        )
        if is_overlap:
            return True, None

    if index < len(ranges):
        is_overlap = (
            query[1] - ranges[index][0] > (query[1] - query[0]) * overlap_ratio
        )
        if is_overlap:
            return True, None

    # overlapping on existing ranges
    is_overlap_left = False
    if index > 0:
        is_overlap_left = (
            ranges[index - 1][1] - query[0]
            > (ranges[index - 1][1] - ranges[index - 1][0]) * overlap_ratio
        )

    is_overlap_right = False
    if index < len(ranges):
        is_overlap_right = (
            query[1] - ranges[index][0]
            > (ranges[index][1] - ranges[index][0]) * overlap_ratio
        )

    if is_overlap_left or is_overlap_right:
        if is_overlap_left and not is_overlap_right:
            ranges.insert(index, query)
            ranges.pop(index - 1)
            indexes.insert(index, segment_index)
            dindex = indexes.pop(index - 1)
            return True, dindex
        elif is_overlap_right and not is_overlap_left:
            ranges.insert(index, query)
            ranges.pop(index + 1)
            indexes.insert(index, segment_index)
            dindex = indexes.pop(index + 1)
            return True, dindex
        else:
            return True, None
    else:
        ranges.insert(index, query)
        indexes.insert(index, segment_index)
        return False, None


def is_punctuation(c: str, eos_only: bool = False) -> bool:
    """
    Return True if the given character is a punctuation.

    Args:
      c:
        The given character.
      eos_only:
        If True the punctuations are only those indicating end of a sentence (,.?! for now).
    """
    if eos_only:
        return c in PUCTUATIONS["eos"]
    return c in PUCTUATIONS["all"]


def str2bool(v):
    """Used in argparse.ArgumentParser.add_argument to indicate
    that a type is a bool type and user can enter

        - yes, true, t, y, 1, to represent True
        - no, false, f, n, 0, to represent False

    See https://stackoverflow.com/questions/15008758/parsing-boolean-values-with-argparse  # noqa
    """
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")
