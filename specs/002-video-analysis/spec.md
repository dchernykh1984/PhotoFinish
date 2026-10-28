# Feature Specification: Finding riders in the video (experimental)

**Feature Branch**: `feat/live-video-editor`

**Created**: 2026-10-29

**Status**: Draft -- experimental, off by default

**Input**: ChronometerPython issue [#49](https://github.com/dchernykh1984/ChronometerPython/issues/49),
comment 8. Maintainer's decisions of 2026-10-28:

- Lay the ground for analysing the video with neural networks on models downloaded beforehand and
  run on the referee's computer.
- Experimental: a rider's crossing is the moment they cross the vertical centre line of the frame.
- Experimental: a hint of where someone is in the picture -- a motion sensor that ignores leaves
  moving in the wind -- and "next rider" / "previous rider". Index the video and look by hand only
  at the stretches where someone passed: usually more than 90% of a finish video is empty
  landscape.
- The main function stays timing by hand (specification 001); everything here only helps the
  referee find the moments to look at.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Jump from rider to rider (Priority: P1)

With analysis on, PhotoFinish indexes each camera's video in the background as it is recorded,
marking the stretches where a rider is in view. The timeline shows them; "Next rider" and "Previous
rider" jump to the start of the next or previous stretch. The referee looks only where someone
passed.

**Why this priority**: It is what saves the referee's time on hours of mostly empty video, and the
other story builds on the same index.

**Independent Test**: The test camera shows an empty, swaying scene with a rider-shaped object
passing three times: the index has three stretches, "Next rider" visits each in turn, and the
swaying alone marks nothing.

**Acceptance Scenarios**:

1. **Given** analysis on and recording, **Then** the index follows the recording within 10 s and
   the timeline shows the stretches.
2. **Given** the video at some moment, **When** the referee presses "Next rider", **Then** the video
   moves to the start of the next stretch; "Previous rider" moves back.
3. **Given** leaves or grass moving in the wind and no one passing, **Then** no stretch is marked.
4. **Given** a detection model file installed, **Then** stretches are where the model sees a person
   or a bicycle; **Given** none, **Then** they come from motion inside the zone the referee drew
   around the line, ignoring motion that is small or does not move across the zone.
5. **Given** the analysis falls behind or fails, **Then** recording and timing by hand are not
   affected and the referee sees how far the index has got.

---

### User Story 2 - Suggested crossings on the centre line (Priority: P2)

With a detection model, PhotoFinish follows each detected rider and, when the front of the rider
crosses the camera's finish line (the vertical centre line unless the referee drew another),
suggests a crossing at the interpolated moment. Suggestions are a list of their own. The referee
looks at each, types the number and accepts it into the output, or dismisses it.

**Why this priority**: It points at the exact frames to check and gives a first time to start from;
it needs Story 1's index and a model, and its quality is unproven, hence experimental.

**Independent Test**: The test camera moves a detectable object across the centre line at a known
moment: one suggestion appears within one frame interval of it.

**Acceptance Scenarios**:

1. **Given** a rider crossing the finish line in view, **Then** one suggestion is listed with its
   interpolated time and the camera.
2. **Given** a suggestion, **When** the referee types a number and accepts it, **Then** a crossing is
   added to the output (specification 001) and the journal says it came from a suggestion of
   that model.
3. **Given** a suggestion, **When** the referee dismisses it, **Then** it leaves the list and nothing
   is written to the output.
4. **Given** two riders crossing close together, **Then** each gets a suggestion of their own when
   the model tells them apart; a missed one is timed by hand as always.

### Edge Cases

- No model file: the motion index works; suggestions are not offered, and the referee is told why.
- A model file that does not load or has the wrong shape: analysis says so and stays off; nothing
  else is affected.
- Night, rain, the sun low in the lens: the index may miss riders; the referee can always scroll
  by hand.
- A camera at a frame rate higher than the analysis can follow: frames are sampled, and a
  suggestion's time is refined on the recorded frames around it.
- Spectators standing at the line: they are people, so the index marks them; the zone around the
  line and the "moves across the zone" rule keep standing people from making suggestions.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Analysis is off by default and turned on in the settings as experimental.
- **FR-002**: Analysis runs in a process of its own, below the recorder in priority, and never
  makes recording or the window wait (constitution, principle VI).
- **FR-003**: Models are ONNX files the referee downloads beforehand and chooses in the settings;
  PhotoFinish never downloads anything. The first model supported is a COCO object detector with
  a licence that allows any use (YOLOX, Apache-2.0); the classes person and bicycle count as
  riders.
- **FR-004**: The index stores, per camera, the stretches where a rider is in view, next to the
  recording, so it survives a restart and is not computed twice.
- **FR-005**: Without a model, the index comes from motion inside a zone the referee draws around
  the finish line; motion that is small or does not travel across the zone is ignored.
- **FR-006**: "Next rider" and "Previous rider" move the video between stretches, from the keyboard
  too.
- **FR-007**: With a model, a detected rider whose front crosses the finish line between two
  sampled frames gives a suggestion timed by the interpolation of specification 001, FR-013.
- **FR-008**: Suggestions are listed apart from the output; accepting one needs the referee's number
  and adds a crossing through the output's usual path; the journal records the model and the
  frames.
- **FR-009**: The referee sees how far the index has got for each camera.

### Key Entities

- **Model**: an ONNX file, its name and the classes that count as riders.
- **Index**: per camera, stretches of time with a rider in view.
- **Suggestion**: a camera, an interpolated time, the frames and the model it came from.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the test scene, the index marks exactly the passes and nothing for the swaying,
  proven by tests.
- **SC-002**: With analysis running on two cameras, recording keeps every frame and the window
  keeps answering, proven by a test that loads the analysis process.
- **SC-003**: On the test scene with a detectable object, each crossing of the centre line gives one
  suggestion within one frame interval, proven by tests with a small model made for the tests.

## Assumptions

- onnxruntime and numpy have wheels for every release platform; OpenCV does not (no Windows on ARM)
  and is not used.
- The model is run on the CPU; a graphics card is a later improvement.
- Reading bib numbers from the picture is a later feature.
