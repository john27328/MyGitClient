"""Local repository workspace management."""

from mygitclient.workspace.discovery import (
    LinkedRepositoriesSnapshot,
    WorkspaceDiscoveryService,
)
from mygitclient.workspace.manager import (
    LinkedRepository,
    WorkspaceManager,
    discover_linked_repositories,
    find_repository_root,
)

__all__ = [
    "LinkedRepository",
    "LinkedRepositoriesSnapshot",
    "WorkspaceManager",
    "WorkspaceDiscoveryService",
    "discover_linked_repositories",
    "find_repository_root",
]
