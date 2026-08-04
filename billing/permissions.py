from rest_framework.permissions import BasePermission

from billing import entitlements


def HasFeature(feature_key: str):
    """Factory returning a DRF BasePermission that gates on a billing feature.

    Usage:
        permission_classes = [IsAuthenticated, IsCreator, HasFeature('creator_analytics')]
    """
    class _HasFeature(BasePermission):
        message = 'Your current plan does not include access to this feature.'

        def has_permission(self, request, view):
            return entitlements.has_feature(request.user, feature_key)

    _HasFeature.__name__ = f'HasFeature_{feature_key}'
    return _HasFeature
