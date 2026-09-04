{# 
  dbt's default behaviour prefixes the target schema onto any custom schema,
  producing names like staging_staging. Since this project already has purpose-
  built schemas in Postgres (raw, staging, intermediate, marts), we override
  that to use the configured name directly.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}