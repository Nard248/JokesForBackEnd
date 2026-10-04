"""Bounded content exploration/export using the existing creator attribution."""
import csv
import io
from datetime import timedelta

from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.permissions import HasFeature
from creator_insights.throttles import CreatorInsightsThrottle
from creator_insights.workbench import MEASUREMENT_NOTES, SORTS, content_queryset, content_row
from jokes.serving import allowed_tiers


class WorkbenchQuerySerializer(serializers.Serializer):
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    period = serializers.ChoiceField(choices=['week', 'month', 'quarter', 'year'], default='month')
    joke_format = serializers.SlugField(required=False, max_length=50)
    language = serializers.CharField(required=False, max_length=10)
    theme = serializers.SlugField(required=False, max_length=100)
    category = serializers.SlugField(required=False, max_length=50)
    q = serializers.CharField(required=False, max_length=200)
    sort = serializers.ChoiceField(choices=list(SORTS), default='newest')
    page_size = serializers.IntegerField(default=25, min_value=1, max_value=100)
    page = serializers.IntegerField(default=1, min_value=1)

    def validate(self, data):
        today = timezone.now().date()
        end = data.get('end', today)
        days = {'week': 7, 'month': 30, 'quarter': 90, 'year': 365}[data['period']]
        try:
            start = data['start'] if 'start' in data else end - timedelta(days=days - 1)
        except OverflowError:
            raise serializers.ValidationError('The date window starts before the earliest supported date.') from None
        if end > today or start > end or (end - start).days >= 366:
            raise serializers.ValidationError('Choose a past date window of at most 366 days, with start before end.')
        data.update(start=start, end=end)
        return data


class ContentPagination(PageNumberPagination):
    page_size_query_param = 'page_size'
    page_size = 25
    max_page_size = 100


WORKBENCH_SCHEMA = inline_serializer(name='CreatorContentPage', fields={
    'count': serializers.IntegerField(),
    'next': serializers.CharField(allow_null=True),
    'previous': serializers.CharField(allow_null=True),
    'results': serializers.ListField(child=serializers.DictField()),
    'window': serializers.DictField(),
    'measurement_notes': serializers.ListField(child=serializers.CharField()),
})


class CreatorContentView(APIView):
    permission_classes = [IsAuthenticated, HasFeature('creator_content_explorer')]
    throttle_classes = [CreatorInsightsThrottle]

    def validated_filters(self, request):
        serializer = WorkbenchQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    @extend_schema(parameters=[WorkbenchQuerySerializer], responses={200: WORKBENCH_SCHEMA})
    def get(self, request):
        filters = self.validated_filters(request)
        paginator = ContentPagination()
        queryset = content_queryset(request.user, filters).filter(content_tier__in=allowed_tiers(request))
        page = paginator.paginate_queryset(queryset, request, view=self)
        response = paginator.get_paginated_response([content_row(joke) for joke in page])
        response.data['window'] = {
            'start': filters['start'].isoformat(), 'end': filters['end'].isoformat(), 'timezone': 'UTC',
        }
        response.data['measurement_notes'] = MEASUREMENT_NOTES
        response['Cache-Control'] = 'private, no-store'
        return response


def csv_value(value):
    # Spreadsheet apps execute formula-prefixed cells even inside CSV quotes.
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


class CreatorContentExportView(CreatorContentView):
    permission_classes = [IsAuthenticated, HasFeature('creator_content_explorer'), HasFeature('creator_exports')]
    MAX_ROWS = 1000

    @extend_schema(parameters=[WorkbenchQuerySerializer], responses={(200, 'text/csv'): str})
    def get(self, request):
        filters = self.validated_filters(request)
        queryset = content_queryset(request.user, filters).filter(content_tier__in=allowed_tiers(request))
        if queryset.count() > self.MAX_ROWS:
            return Response({'detail': 'Narrow the filters to export at most 1000 jokes.'}, status=422)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'id', 'text', 'setup', 'punchline', 'format', 'language', 'themes', 'categories',
            'views', 'reactions', 'saves', 'share_initiations', 'metadata_completeness',
            'window_start_utc', 'window_end_utc',
        ])
        for joke in queryset[:self.MAX_ROWS]:
            row = content_row(joke)
            writer.writerow([csv_value(value) for value in [
                row['id'], row['text'], row['setup'], row['punchline'], row['format']['name'],
                row['language']['code'], ', '.join(t['name'] for t in row['themes']),
                ', '.join(t['name'] for t in row['categories']), row['views'], row['reactions'],
                row['saves'], row['share_initiations'], row['metadata_completeness'],
                filters['start'].isoformat(), filters['end'].isoformat(),
            ]])
        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="jokesfor-creator-content.csv"'
        response['Cache-Control'] = 'private, no-store'
        return response
