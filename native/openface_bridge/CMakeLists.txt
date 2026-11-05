cmake_minimum_required(VERSION 3.16)
project(openface_bridge CXX)
set(CMAKE_CXX_STANDARD 17)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

set(OPENFACE_DIR "$ENV{HOME}/DEV/OpenFace" CACHE PATH "OpenFace checkout, built in its build/ folder")
find_package(OpenCV 4.0 REQUIRED COMPONENTS core imgproc calib3d highgui objdetect)
find_package(dlib REQUIRED)
find_package(Boost REQUIRED COMPONENTS filesystem system)
find_library(OPENBLAS_LIB openblas REQUIRED)

add_executable(openface_bridge bridge.cpp)
target_include_directories(openface_bridge PRIVATE
  ${OPENFACE_DIR}/lib/local/LandmarkDetector/include
  ${OPENFACE_DIR}/lib/local/FaceAnalyser/include
  ${OPENFACE_DIR}/lib/local/Utilities/include
  ${OpenCV_INCLUDE_DIRS} ${Boost_INCLUDE_DIRS})
target_link_libraries(openface_bridge PRIVATE
  ${OPENFACE_DIR}/build/lib/local/FaceAnalyser/libFaceAnalyser.a
  ${OPENFACE_DIR}/build/lib/local/LandmarkDetector/libLandmarkDetector.a
  ${OPENFACE_DIR}/build/lib/local/Utilities/libUtilities.a
  ${OpenCV_LIBS} dlib::dlib ${Boost_LIBRARIES} ${OPENBLAS_LIB})
