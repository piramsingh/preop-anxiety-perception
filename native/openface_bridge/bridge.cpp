// Reads frames on stdin and writes one JSON line per frame on stdout. Runs entirely locally.
//
// Input, repeated: uint32 width, uint32 height, float64 timestamp, then width*height*3 BGR bytes.
// Output: {"ready":true} once models load, then
//         {"t":..,"detected":..,"confidence":..,"aus":{"AU01":..},"present":{"AU01":0}}
//
// This program calls OpenFace's libraries and contains none of its code. OpenFace is installed
// separately under its own noncommercial research license.
#include <FaceAnalyser.h>
#include <LandmarkCoreIncludes.h>

#include <opencv2/imgproc.hpp>

#include <cstdint>
#include <cstdio>
#include <iostream>
#include <string>
#include <unistd.h>
#include <vector>

static bool read_exact(void *buffer, size_t size) {
    return fread(buffer, 1, size, stdin) == size;
}

static void write_aus(FILE *out, const std::vector<std::pair<std::string, double>> &values) {
    bool first = true;
    for (const auto &entry : values) {
        fprintf(out, "%s\"%s\":%.4f", first ? "" : ",", entry.first.c_str(), entry.second);
        first = false;
    }
}

int main(int argc, char **argv) {
    if (argc < 2) {
        std::cerr << "usage: openface_bridge <OpenFace build/bin directory>" << std::endl;
        return 2;
    }
    // OpenFace prints to stdout while loading. Keep stdout clean for the JSON protocol.
    int protocol_fd = dup(STDOUT_FILENO);
    dup2(STDERR_FILENO, STDOUT_FILENO);
    FILE *out = fdopen(protocol_fd, "w");

    // OpenFace finds its models relative to the path of the first argument.
    std::vector<std::string> arguments{std::string(argv[1]) + "/FeatureExtraction"};
    LandmarkDetector::FaceModelParameters detector_params(arguments);
    LandmarkDetector::CLNF face_model(detector_params.model_location);
    if (!face_model.loaded_successfully) {
        std::cerr << "Could not load the OpenFace landmark models" << std::endl;
        return 1;
    }
    FaceAnalysis::FaceAnalyserParameters analyser_params(arguments);
    FaceAnalysis::FaceAnalyser analyser(analyser_params);

    fprintf(out, "{\"ready\":true}\n");
    fflush(out);

    while (true) {
        uint32_t width = 0, height = 0;
        double timestamp = 0.0;
        if (!read_exact(&width, 4) || !read_exact(&height, 4) || !read_exact(&timestamp, 8)) {
            return 0;  // The pipeline closed stdin.
        }
        cv::Mat frame(static_cast<int>(height), static_cast<int>(width), CV_8UC3);
        if (!read_exact(frame.data, static_cast<size_t>(width) * height * 3)) {
            return 0;
        }
        cv::Mat_<uchar> gray;
        cv::cvtColor(frame, gray, cv::COLOR_BGR2GRAY);

        bool detected = LandmarkDetector::DetectLandmarksInVideo(frame, face_model, detector_params, gray);
        analyser.AddNextFrame(frame, face_model.detected_landmarks, face_model.detection_success, timestamp, true);

        fprintf(out, "{\"t\":%.4f,\"detected\":%s,\"confidence\":%.4f,\"aus\":{", timestamp,
                detected ? "true" : "false", face_model.detection_certainty);
        write_aus(out, analyser.GetCurrentAUsReg());
        fprintf(out, "},\"present\":{");
        write_aus(out, analyser.GetCurrentAUsClass());
        fprintf(out, "}}\n");
        fflush(out);
    }
}
