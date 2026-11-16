# Copyright (c) 2019 The STE||AR-Group
#
# SPDX-License-Identifier: BSL-1.0
# Distributed under the Boost Software License, Version 1.0. (See accompanying
# file LICENSE_1_0.txt or copy at http://www.boost.org/LICENSE_1_0.txt)

add_hpx_executable(
  partitioned_vector_front_report_test INTERNAL_FLAGS
  SOURCES partitioned_vector_front_report.cpp
  DEPENDENCIES partitioned_vector_component
  EXCLUDE_FROM_ALL
  FOLDER "Benchmarks/Components/Containers/PartitionedVector"
)

add_hpx_performance_test(
  "components.partitioned_vector" partitioned_vector_front_report
  THREADS_PER_LOCALITY 1
  --partition_size=16
  --iterations=1000000
  --test_count=20
)

add_hpx_executable(
  partitioned_vector_get_value_report_test INTERNAL_FLAGS
  SOURCES partitioned_vector_get_value_report.cpp
  DEPENDENCIES partitioned_vector_component
  EXCLUDE_FROM_ALL
  FOLDER "Benchmarks/Components/Containers/PartitionedVector"
)

add_hpx_performance_test(
  "components.partitioned_vector" partitioned_vector_get_value_report
  THREADS_PER_LOCALITY 1
  --partition_size=16
  --iterations=1000000
  --test_count=20
)
