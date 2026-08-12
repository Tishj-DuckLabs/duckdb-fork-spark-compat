#pragma once
#include "duckdb/common/case_insensitive_map.hpp"
#include "duckdb/common/common.hpp"

namespace duckdb {
// Spark's SET/UNSET TBLPROPERTIES payload. UNSET only carries keys, so values are empty for it.
struct SparkTblPropertiesAction {
	bool unset = false;
	case_insensitive_map_t<string> properties;
};
} // namespace duckdb
