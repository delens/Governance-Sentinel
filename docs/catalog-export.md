# Catalog export

`python -m governance_sentinel export-catalog` writes files a catalog can import. It does not open a socket, and it does not import a DataHub or Collibra SDK. The command reads the glossary, the ownership matrix, and the column-lineage declaration already in this repository.

```bash
python -m governance_sentinel export-catalog --target datahub --out catalog_export
python -m governance_sentinel export-catalog --target collibra --out catalog_export
```

| Target | Files |
| --- | --- |
| `datahub` | `datahub_mcp.json` |
| `collibra` | `collibra_assets.csv`, `collibra_import.json` |

`catalog_export/` is gitignored. A later run overwrites the files in `--out`.

## DataHub

`datahub_mcp.json` is a JSON array of Metadata Change Proposals. That is the file the DataHub file sink writes and the file source reads.

Sources for the shape:

- File sink output, including `aspect.json`: [Saving MCPs to a File](https://docs.datahub.com/docs/advanced/writing-mcps). The example there is one dataset proposal with `entityType`, `entityUrn`, `changeType`, `aspectName`, and `aspect.json`.
- File source: a JSON array of proposals, or a legacy Metadata Change Event with `proposedSnapshot`. [Metadata File](https://docs.datahub.com/docs/generated/ingestion/sources/metadata-file/) and the DataHub support note on [ingesting metadata JSON files](https://support.datahub.com/hc/en-us/articles/58591927345947-Ingesting-Metadata-JSON-Files-from-S3-into-DataHub-Using-the-File-Source).
- Proposal fields: [Metadata Change Proposal](https://docs.datahub.com/docs/advanced/mcp-mcl). `changeType` in this file is `UPSERT`.

This export writes proposals, not the legacy `proposedSnapshot` event. The file source accepts both. A recipe that points `source.type: file` at `datahub_mcp.json`, or `datahub ingest mcps datahub_mcp.json`, is the documented way to load the file. This repository does not run that command.

Each proposal updates one aspect. The file includes:

| Entity | Aspects |
| --- | --- |
| `glossaryNode` `urn:li:glossaryNode:bcbs239RiskData` | `glossaryNodeInfo` |
| one `glossaryTerm` per glossary term | `glossaryTermInfo` (name, definition, parent node, CDE, criticality, tolerance), `ownership`, `status` |
| `dataset` for `core_banking.transactions`, `reference.counterparties`, `staging.risk_transactions`, `risk_mart.exposure_by_entity` | `datasetProperties`, `status`, `ownership`, `schemaMetadata`, `glossaryTerms` where a term is linked, `upstreamLineage` where a column edge comes in |

Schema fields use DataHub's union encoding, for example `com.linkedin.schema.StringType`. `nullable` is true on every field: this export does not claim a column is mandatory. The data-quality rules are what mark a blank as a failure. `isPartOfKey` marks `transaction_id` on the booking extract and on staging, the three aggregate grain columns, and `counterparty_id` on the master. That is the grain used in this prototype, not a database primary key.

`upstreamLineage.fineGrainedLineages` uses `upstreams` and `downstreams` (the current FineGrainedLineage fields), `upstreamType` `FIELD_SET`, and `downstreamType` `FIELD`. `transformOperation` is the word from column lineage: `direct`, `aggregation`, `derivation`, or `filter`. Dataset-level upstreams are `TRANSFORMED`.

Ownership uses `urn:li:corpGroup:<role>` with type `BUSINESS_OWNER` for the data owner and `DATA_STEWARD` for the steward. The slug is the role name. These are roles from `governance/ownership.yml`. They are not CorpUser accounts and not people. Audit stamps use `urn:li:corpuser:governance_sentinel` and time `0`, so the file does not change between runs. That actor is the tool, not a person.

The platform in the dataset URN is `governance_sentinel` and the fabric is `DEV`. `DEV` is there because DataHub requires a fabric and the data is synthetic. It does not mean a bank development environment. Dataset names are the logical names already used for lineage (`core_banking.transactions` and the rest). There is no live warehouse behind them.

A glossary term is attached to the dataset it is physically on. Terms on staging whose column also exists on `core_banking.transactions` are also attached there, because those columns are direct copies. The counterparty term is also attached to `reference.counterparties`, because that master is the source the referential rule checks.

### Limits

- No DataHub server is contacted. The aspects are not validated by GMS. A field that a future model rejects would fail at ingest time, not here.
- `parentNode` is included on `glossaryTermInfo`. Older DataHub builds that do not know that field will reject the aspect.
- The file does not emit pipelines, data jobs, tags, domains, or assertions. Rule results stay in the audit PDF and in the OpenLineage file the audit already writes.
- Column lineage is the declared edge list in `governance_sentinel/column_lineage.py`. It is not discovered from SQL.

## Collibra

Two files, one import shape each.

`collibra_assets.csv` follows the asset-import wizard: one header row, one asset per row. Data element rows come first, then business terms, so the term's relation names an asset that is also in the file.

Column headers:

- Asset identity: `Name`, `Full Name`, `Community`, `Domain`, `Domain Type`, `Asset Type`, `Status`
- Attributes: `Definition`, `Criticality`, `Source System`, `Tolerance Threshold`, `Data Owner Role`, `Data Steward Role`, `CDE`, `Physical Dataset`, `Physical Column`, `DQ Rules`
- Relation: `[Business Term] represents [Data Element]`

The relation header is the import v2 form `[source asset type] role [target asset type]`, documented in [Import v2 overview](https://productresources.collibra.com/docs/collibra/2024.10/Content/ImportAndExport/co_import-v2-overview.htm). The wizard itself is [Import assets](https://productresources.collibra.com/docs/collibra/latest/Content/ImportAndExport/ta_import-assets.htm). Collibra maps headers by name. A header it does not know stays unmapped until someone maps it. `Definition` is an out-of-the-box attribute. `Criticality`, `Source System`, `Tolerance Threshold`, `Data Owner Role`, and `Data Steward Role` are columns for that mapping step. They are not created in a Collibra instance by this repository.

`collibra_import.json` is a JSON array of Import API commands: one community, two domains, then an asset command per data element and per business term. The command fields follow [Importing assets](https://developer.collibra.com/api/guides/import-api/import-commands/importing-assets): `resourceType`, `identifier` (name plus domain plus community), `type.name`, `status.name`, `attributes` keyed by attribute type name, and `relations` keyed by a fully qualified relation type.

The relation key in the JSON is:

```text
Business Term:represents:is represented by:Data Element:TARGET
```

That is the documented form `{source type}:{role}:{co-role}:{target type}:{TARGET}`. `:TARGET` means the imported business term is the source and the listed data element is the target.

Fixed names in both files:

| Object | Name |
| --- | --- |
| Community | Governance Sentinel |
| Business-term domain | Risk Data Glossary, domain type Glossary |
| Data-element domain | Risk Data Elements, domain type Physical Data Dictionary |
| Business term asset type | Business Term |
| Data element asset type | Data Element |
| Status | Candidate |

`Glossary` and `Physical Data Dictionary` are domain types in Collibra's out-of-the-box Data Governance operating model. `Business Term` and `Data Element` are out-of-the-box asset types. Status `Candidate` is an out-of-the-box status. This repository has not submitted the file to a Collibra instance, so a target that renamed any of those will need the header mapped or the JSON key edited.

The data element name is `{physical dataset}.{physical column}`, for example `staging.risk_transactions.transaction_id`. The business term name is the glossary term. The relation cell on a term row is the data element name.

### Limits

- Owner and steward are role names in `Data Owner Role`, `Data Steward Role`, and in the JSON `Note` attribute. They are not Collibra responsibilities. A responsibility expects a user id or a group id, and the ownership matrix does not contain accounts.
- The out-of-the-box "represents / is represented by" relation is defined between Business Asset and Data Asset. Business Term and Data Element inherit it. If the import rejects the relation key, substitute the relation's public id, or the parent form `Business Asset:represents:is represented by:Data Asset:TARGET`. No relation-type UUID is written here, because this export does not invent one.
- Attribute keys `Definition` and `Note` are out-of-the-box names. A model that does not assign `Definition` to Data Element will skip or reject that attribute. The same text is also in `Note`.
- There is no Collibra community, domain, or asset id in the file. Identifiers are names.
- Nothing is sent to Collibra. Loading the file is an import in the target, using the wizard for the CSV or the Import API for the JSON.

## What both files leave out

The export is the glossary, the ownership roles, the physical column, and the declared column lineage. It is not a copy of a bank's production catalog, and it does not add systems that this prototype does not model.
