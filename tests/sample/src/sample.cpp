#include "sample.h"

#include <fmt/format.h>

namespace sample {

    int add(int left, int right) {
        return left + right;
    }

    std::string greet(const std::string &name) {
        return fmt::format("hello, {}", name);
    }

} // namespace sample
