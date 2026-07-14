// C++/pybind11 accelerator for inference/exported_model.py::_linear_batched()
// - the batched linear-layer primitive (weights (N,out,in) @ input (N,in)
// + bias (N,out)), the most call-heavy primitive in main.py's per-bar
// inference hot path (see development/Problems.md #32). NumPy's own
// einsum-based implementation is the always-correct, always-available
// path; this module is an OPTIONAL accelerator inference/exported_model.py
// falls back away from on any import/call failure - never a hard
// dependency (requirements.txt is untouched by this).

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <stdexcept>

namespace py = pybind11;

// output[n, o] = sum_i weights[n, o, i] * input[n, i] + bias[n, o]
// Mirrors inference/exported_model.py::_linear_batched()'s
// np.einsum("noi,ni->no", weights_stack, current) + bias_stack exactly -
// same math, same output, only the loop is compiled instead of
// interpreted/dispatched through NumPy's einsum machinery.
py::array_t<double> linear_batched(
    py::array_t<double, py::array::c_style | py::array::forcecast> weights,
    py::array_t<double, py::array::c_style | py::array::forcecast> input,
    py::array_t<double, py::array::c_style | py::array::forcecast> bias
) {
    auto w = weights.unchecked<3>();  // (N, out_features, in_features)
    auto x = input.unchecked<2>();    // (N, in_features)
    auto b = bias.unchecked<2>();     // (N, out_features)

    py::ssize_t n_models = w.shape(0);
    py::ssize_t out_features = w.shape(1);
    py::ssize_t in_features = w.shape(2);

    if (x.shape(0) != n_models || x.shape(1) != in_features) {
        throw std::runtime_error("linear_batched: input shape does not match weights");
    }
    if (b.shape(0) != n_models || b.shape(1) != out_features) {
        throw std::runtime_error("linear_batched: bias shape does not match weights");
    }

    py::array_t<double> result({n_models, out_features});
    auto r = result.mutable_unchecked<2>();

    for (py::ssize_t n = 0; n < n_models; ++n) {
        for (py::ssize_t o = 0; o < out_features; ++o) {
            double sum = 0.0;
            for (py::ssize_t i = 0; i < in_features; ++i) {
                sum += w(n, o, i) * x(n, i);
            }
            r(n, o) = sum + b(n, o);
        }
    }
    return result;
}

PYBIND11_MODULE(cpp_inference, m) {
    m.doc() = "Optional C++/pybind11 accelerator for inference/exported_model.py's batched linear layer";
    m.def(
        "linear_batched", &linear_batched,
        "Batched linear layer: weights (N,out,in) @ input (N,in) + bias (N,out) -> (N,out)"
    );
}
