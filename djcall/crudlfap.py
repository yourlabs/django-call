'''
from crudlfap import crudlfap

from django_filters import filters
import django_tables2 as tables

from .models import Execution, Task


class TaskDetailView(crudlfap.DetailView):
    display_fields_extra = ['callback_code']

    def get_children_list_view(self):
        view = crudlfap.ListView.clone(
            model=Task,
            object_list=self.object.task_set.all(),
            table_fields=[
                'spooled',
                'callback',
                'status',
            ],
            table_meta_attributes_extra=dict(
                page_field='children_page',
            ),
        )(request=self.request)
        self.children_list_view = view
        return view

    def get_execution_list_view(self):
        view = crudlfap.site[Execution]['list'].clone(
            table_columns=dict(
                traceback=tables.TemplateColumn(
                    template_code='<pre>{{ value }}</pre>'
                ),
                output=tables.TemplateColumn(
                    template_code='<pre>{{ value }}</pre>'
                ),
            ),
        )(request=self.request)
        self.execution_list_view = view
        return view


crudlfap.Router(
    Task,
    material_icon='local_laundry_service',
    views=[
        crudlfap.ListView.clone(
            filterset_extra_class_attributes=dict(
                status=filters.ChoiceFilter(choices=Task.STATUS_CHOICES)
            ),
            table_fields=[
                'id',
                'callback',
                'spooled',
                'status',
            ],
            search_fields=[
                'callback',
                'output',
            ],
        ),
        crudlfap.UpdateView,
        crudlfap.DeleteObjectsView,
        crudlfap.DeleteView,
        TaskDetailView,
    ]
).register()


crudlfap.Router(
    Execution,
    material_icon='autorenew',
    views=[
        crudlfap.DetailView.clone(
            code_fields=['output', 'traceback', 'callback_code'],
        ),
        crudlfap.ListView.clone(
            table_meta_attributes_extra=dict(
                page_field='execution_page',
            ),
            table_columns=dict(
                callback=tables.Column(accessor='task.callback'),
            ),
            table_fields=[
                'status',
                'started',
                'ended',
            ],
            queryset=Execution.objects.all().select_related('task'),
        ),
    ],
).register()
'''
