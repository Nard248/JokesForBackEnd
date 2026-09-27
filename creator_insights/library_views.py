"""Owner-only creator workspace; private records remain readable after cancellation."""
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.permissions import HasFeature
from creator_insights.library import (
    collection_row,
    create_metadata_requests,
    delete_note,
    require_jokes,
    save_collection,
    save_note,
    visible_creator_jokes,
)
from creator_insights.library_serializers import (
    CollectionSerializer,
    CollectionWriteSerializer,
    MetadataRequestSerializer,
    MetadataRequestWriteSerializer,
    NoteSerializer,
    NoteWriteSerializer,
)
from creator_insights.models import CreatorCollection, CreatorMetadataRequest, CreatorWorkspaceNote
from creator_insights.throttles import CreatorInsightsThrottle


class LibraryPageQuery(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=25)


class LibraryPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100


def page_schema(name, result_serializer, *, notes=False):
    fields = {
        'count': serializers.IntegerField(), 'next': serializers.CharField(allow_null=True),
        'previous': serializers.CharField(allow_null=True), 'results': result_serializer(many=True),
    }
    if notes:
        fields['unavailable_count'] = serializers.IntegerField()
    return inline_serializer(name=name, fields=fields)


class LibraryView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [CreatorInsightsThrottle]

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.request.method in ('POST', 'PATCH', 'PUT'):
            permissions.append(HasFeature('creator_content_explorer')())
        return permissions

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response

    def paginate(self, request, queryset):
        query = LibraryPageQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        paginator = LibraryPagination()
        return paginator, paginator.paginate_queryset(queryset, request, view=self)

    def collection_data(self, request, collections):
        target_ids = {entry.joke_id for collection in collections for entry in collection.entries.all()}
        visible_items = {
            row['id']: (row['text'] or row['setup'] or row['format__name'])[:180]
            for row in visible_creator_jokes(request).filter(pk__in=target_ids).values('id', 'text', 'setup', 'format__name')
        }
        return CollectionSerializer([collection_row(collection, visible_items) for collection in collections], many=True).data


class CreatorWorkspaceNoteView(LibraryView):
    @extend_schema(responses=NoteSerializer)
    def get(self, request, joke_id):
        require_jokes(request, [joke_id])
        note = CreatorWorkspaceNote.objects.filter(owner=request.user, joke_id=joke_id).first()
        if note is None:
            return Response({'joke_id': joke_id, 'private_note': '', 'updated_at': None})
        return Response(NoteSerializer(note).data)

    @extend_schema(request=NoteWriteSerializer, responses=NoteSerializer)
    def patch(self, request, joke_id):
        serializer = NoteWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = save_note(request, joke_id, serializer.validated_data['private_note'])
        return Response(NoteSerializer(note).data)

    @extend_schema(responses={204: None})
    def delete(self, request, joke_id):
        delete_note(request.user, joke_id)
        return Response(status=204)


class CreatorWorkspaceNotesView(LibraryView):
    @extend_schema(parameters=[LibraryPageQuery], responses=page_schema('CreatorNotesPage', NoteSerializer, notes=True))
    def get(self, request):
        own = CreatorWorkspaceNote.objects.filter(owner=request.user)
        visible = own.filter(joke_id__in=visible_creator_jokes(request).values('pk'))
        paginator, notes = self.paginate(request, visible)
        response = paginator.get_paginated_response(NoteSerializer(notes, many=True).data)
        response.data['unavailable_count'] = own.count() - paginator.page.paginator.count
        return response


class CreatorCollectionsView(LibraryView):
    @extend_schema(operation_id='creator_collections_list', parameters=[LibraryPageQuery], responses=page_schema('CreatorCollectionsPage', CollectionSerializer))
    def get(self, request):
        queryset = CreatorCollection.objects.filter(owner=request.user).prefetch_related('entries')
        paginator, collections = self.paginate(request, queryset)
        return paginator.get_paginated_response(self.collection_data(request, collections))

    @extend_schema(request=CollectionWriteSerializer, responses={201: CollectionSerializer})
    def post(self, request):
        serializer = CollectionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        collection = save_collection(request, serializer.validated_data)
        return Response(self.collection_data(request, [collection])[0], status=201)


class CreatorCollectionView(LibraryView):
    @extend_schema(responses=CollectionSerializer)
    def get(self, request, pk):
        collection = get_object_or_404(CreatorCollection.objects.prefetch_related('entries'), owner=request.user, pk=pk)
        return Response(self.collection_data(request, [collection])[0])

    @extend_schema(request=CollectionWriteSerializer, responses=CollectionSerializer)
    def patch(self, request, pk):
        serializer = CollectionWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        collection = save_collection(request, serializer.validated_data, collection_id=pk)
        return Response(self.collection_data(request, [collection])[0])

    @extend_schema(responses={204: None})
    def delete(self, request, pk):
        collection = get_object_or_404(CreatorCollection, owner=request.user, pk=pk)
        collection.delete()
        return Response(status=204)


class CreatorMetadataRequestsView(LibraryView):
    @extend_schema(parameters=[LibraryPageQuery], responses=page_schema('CreatorMetadataRequestsPage', MetadataRequestSerializer))
    def get(self, request):
        queryset = CreatorMetadataRequest.objects.filter(
            owner=request.user, joke_id__in=visible_creator_jokes(request).values('pk'),
        )
        paginator, reviews = self.paginate(request, queryset)
        return paginator.get_paginated_response(MetadataRequestSerializer(reviews, many=True).data)

    @extend_schema(request=MetadataRequestWriteSerializer, responses={201: inline_serializer(
        name='CreatorMetadataRequestBatch', fields={'results': MetadataRequestSerializer(many=True)},
    )})
    def post(self, request):
        serializer = MetadataRequestWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reviews = create_metadata_requests(request, serializer.validated_data)
        return Response({'results': MetadataRequestSerializer(reviews, many=True).data}, status=201)
