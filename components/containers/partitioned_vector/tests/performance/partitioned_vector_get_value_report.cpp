//  Copyright (c) 2026
//
//  SPDX-License-Identifier: BSL-1.0
//  Distributed under the Boost Software License, Version 1.0.

#include <hpx/config.hpp>

#if !defined(HPX_COMPUTE_DEVICE_CODE)

// Deliberately include the declaration rather than the implementation header.
// The int/std::vector<int> specialization is instantiated by HPX's
// partitioned_vector_component library. This helps avoid inlining get_value(0)
// into the benchmark translation unit (provided LTO is disabled).
#include <hpx/components/containers/partitioned_vector/partitioned_vector_component_decl.hpp>
#include <hpx/init.hpp>
#include <hpx/modules/testing.hpp>

#include <cstddef>
#include <cstdint>
#include <iostream>
#include <vector>

int hpx_main(hpx::program_options::variables_map& vm)
{
    std::size_t const partition_size =
        vm["partition_size"].as<std::size_t>();
    std::size_t const iterations = vm["iterations"].as<std::size_t>();
    std::size_t const warmup_iterations =
        vm["warmup_iterations"].as<std::size_t>();
    int const test_count = vm["test_count"].as<int>();

    hpx::util::perftests_init(vm);

    if (partition_size == 0 || iterations == 0 || test_count <= 0)
    {
        std::cerr << "partition_size, iterations, and test_count must be "
                     "positive\n";
        hpx::local::finalize();
        return 1;
    }

    using partition_type =
        hpx::server::partitioned_vector<int, std::vector<int>>;

    constexpr int element_value = 7;
    std::vector<partition_type::size_type> sizes{partition_size};
    partition_type partition(0, sizes, element_value);
    partition_type const& const_partition = partition;

    if (const_partition.get_value(0) != element_value)
    {
        std::cerr << "Unexpected get_value(0) value\n";
        hpx::local::finalize();
        return 1;
    }

    // Accumulate returned values to make the work observable without putting
    // volatile accesses, atomics, or output inside the measured loop.
    std::uint64_t checksum = 0;
    for (std::size_t i = 0; i < warmup_iterations; ++i)
    {
        checksum += static_cast<std::uint64_t>(const_partition.get_value(0));
    }

    hpx::util::perftests_report("partitioned_vector_get_value", "server_direct",
        test_count, [&]() {
            std::uint64_t sample_sum = 0;
            for (std::size_t i = 0; i < iterations; ++i)
            {
                sample_sum +=
                    static_cast<std::uint64_t>(const_partition.get_value(0));
            }
            checksum += sample_sum;
        });

    // With --detailed_bench, stdout is reserved for performance JSON.
    hpx::util::perftests_print_times();
    std::cerr << "partition_size=" << partition_size
              << " iterations=" << iterations << " test_count=" << test_count
              << " warmup_iterations=" << warmup_iterations
              << " checksum=" << checksum << '\n';

    return hpx::local::finalize();
}

int main(int argc, char* argv[])
{
    using namespace hpx::program_options;

    options_description cmdline("usage: " HPX_APPLICATION_STRING " [options]");
    cmdline.add_options()
        ("partition_size", value<std::size_t>()->default_value(16),
            "number of elements in the local server partition")
        ("iterations", value<std::size_t>()->default_value(1000000),
            "get_value(0) calls per timed sample")
        ("warmup_iterations", value<std::size_t>()->default_value(10000),
            "get_value(0) calls before the timed samples")
        ("test_count", value<int>()->default_value(20),
            "number of timed samples per launch");

    hpx::util::perftests_cfg(cmdline);

    hpx::local::init_params init_args;
    init_args.desc_cmdline = cmdline;
    init_args.cfg = {"hpx.os_threads=1"};

    return hpx::local::init(hpx_main, argc, argv, init_args);
}

#endif
