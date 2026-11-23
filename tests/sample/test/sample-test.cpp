#include "sample.h"

#include <catch2/catch_test_macros.hpp>

TEST_CASE("add adds two numbers", "[sample]") {
    REQUIRE(sample::add(1, 2) == 3);
    REQUIRE(sample::add(-1, 1) == 0);
}

TEST_CASE("greet formats a name", "[sample]") {
    REQUIRE(sample::greet("world") == "hello, world");
}
