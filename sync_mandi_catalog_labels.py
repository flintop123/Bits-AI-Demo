"""Precompute bilingual mandi catalog labels for instant UI switching."""

from conn.mandi_catalog_labels import MandiCatalogLabelMongo
from services.agriculture_query_service import AgricultureQueryService


def main():
    service = AgricultureQueryService()
    try:
        catalog = service.sync_mandi_catalog_labels()
        print("\nBilingual mandi catalog cache")
        print("------------------------------")
        for field, summary in catalog.items():
            print(
                f"{field}: {summary['observed']} observed, "
                f"{summary['created']} new labels cached"
            )
        print("Language switching is ready without model loading.")
        return 0
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
