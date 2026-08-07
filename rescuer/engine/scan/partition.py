import os

from rescuer.engine.models import FoundFile, RecoverySource, ScanConfig
from rescuer.engine.partition.analyzer import analyze, analyze_boot_area
from rescuer.engine.signatures.registry import SignatureRegistry


def run_partition_scan(
    source: RecoverySource,
    config: ScanConfig,
    registry: SignatureRegistry | None = None,
) -> list[FoundFile]:
    size = source.size or os.path.getsize(source.raw_path())
    result = analyze(source.raw_path(), size)
    files: list[FoundFile] = []
    for p in result.partitions:
        label = f"{p.fs_type.upper()} partition"
        files.append(
            FoundFile(
                name=label,
                size=p.byte_size,
                is_deleted=True,
                found_by="partition",
                fs_type=p.fs_type,
                raw_offset=p.offset,
            )
        )
    if not result.partitions:
        boot = analyze_boot_area(source.raw_path(), size)
        files.append(
            FoundFile(
                name=f"Boot sector: {boot}",
                size=min(size, 512),
                is_deleted=True,
                found_by="partition",
                fs_type=boot,
                raw_offset=0,
            )
        )
    return files
