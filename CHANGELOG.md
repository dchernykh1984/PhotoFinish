# Changelog

## [0.3.2](https://github.com/dchernykh1984/PhotoFinish/compare/v0.3.1...v0.3.2) (2026-11-10)


### Bug Fixes

* **build:** declare camera use so macOS lets the app open a USB camera ([2fe4a58](https://github.com/dchernykh1984/PhotoFinish/commit/2fe4a587d7b9bf66f528406c49b6fe6f51e8cc70))
* **window:** lay the output list's four buttons in two rows so no label is cut ([0eb1030](https://github.com/dchernykh1984/PhotoFinish/commit/0eb10300189c9b628d1c1ece02bef4204c397306))

## [0.3.1](https://github.com/dchernykh1984/PhotoFinish/compare/v0.3.0...v0.3.1) (2026-11-07)


### Bug Fixes

* **ci:** restore the macos release asset, lost to a retired runner label ([aa61c73](https://github.com/dchernykh1984/PhotoFinish/commit/aa61c73eb17996590468c783ad699044999859db))

## [0.3.0](https://github.com/dchernykh1984/PhotoFinish/compare/v0.2.0...v0.3.0) (2026-11-02)


### Features

* **output:** keep a copy of the output after every change ([17a48c7](https://github.com/dchernykh1984/PhotoFinish/commit/17a48c7e82d1a3e2897bb3acd41372e1191cafa3))


### Bug Fixes

* **output:** copy an opened output though its journal refuses ([9348d93](https://github.com/dchernykh1984/PhotoFinish/commit/9348d930293bf9414863627a8ab8d938218c3896))
* **output:** copy an output adopted from its file as the list first writes it ([3a2bf63](https://github.com/dchernykh1984/PhotoFinish/commit/3a2bf63fb51d68bd584581ccb267a4b746424359))
* **output:** copy the output a crash left behind once it is brought up to the state ([853c0f5](https://github.com/dchernykh1984/PhotoFinish/commit/853c0f511b39ed0448ac99d15f9de66096b7de90))
* **output:** copy the output when it is opened if a crash came before its last copy ([d6beaf5](https://github.com/dchernykh1984/PhotoFinish/commit/d6beaf551bd52563a0aee26598d0393255da2c1e))
* **output:** find the newest copy or backup though one goes meanwhile, ties by name ([238740a](https://github.com/dchernykh1984/PhotoFinish/commit/238740a411ec0be7de9a5cf92ff318ee5336be70))
* **output:** keep each output's copies apart and find the newest by its time ([abb3040](https://github.com/dchernykh1984/PhotoFinish/commit/abb30401403d718f0f0c58680d6f01ee79f5cce7))
* **output:** name the copies of an output whose path is not UTF-8 ([b471283](https://github.com/dchernykh1984/PhotoFinish/commit/b471283753e644a94fd760d1b89ec7bc3146d2f2))
* **output:** open the output whatever keeps its newest copy from being read ([f57d9b2](https://github.com/dchernykh1984/PhotoFinish/commit/f57d9b2c49e65813f9a38f3579540bffb454c460))
* **output:** write the copy of the output in one step like the output itself ([f6d64d0](https://github.com/dchernykh1984/PhotoFinish/commit/f6d64d01d52a92e5d1c39e1433433e8eaf32918a))
* **record:** count a segment once its close has named it, not before ([47143f9](https://github.com/dchernykh1984/PhotoFinish/commit/47143f9d8b113c1d85611234970597529000a7a3))
* **record:** count no segment for a name a kill cut short in the list ([204dcd4](https://github.com/dchernykh1984/PhotoFinish/commit/204dcd4ac200a21352f76a6ac7584c75b6e513f2))
* **record:** drop the copy of a recovery that failed, the crash's files being kept ([0ead4f2](https://github.com/dchernykh1984/PhotoFinish/commit/0ead4f2d93889d351a2aff870ae5bfdebebe8399))
* **record:** end in disk_full when the writer's own recovery finds the disk full ([8d01bcd](https://github.com/dchernykh1984/PhotoFinish/commit/8d01bcd3fd87fa720172639b28ca896ab6647a52))
* **record:** find a cut close's own times among others alike, by when they were written ([d69c7ed](https://github.com/dchernykh1984/PhotoFinish/commit/d69c7edf7a4bea5d05dc02d2a4932bbeb7452103))
* **record:** finish a close a crash cut between its two renames ([13a772d](https://github.com/dchernykh1984/PhotoFinish/commit/13a772db9e5d529c6c3ea34cc8f9fba82b4873cf))
* **record:** finish a cut close by the name it wrote first, guessing nothing ([df377b0](https://github.com/dchernykh1984/PhotoFinish/commit/df377b0b7389738948faaf634197ab6981a42278))
* **record:** finish a recovery a kill cut by the name it wrote, not by a guess ([60070e6](https://github.com/dchernykh1984/PhotoFinish/commit/60070e65030506fa0b39bf7ebd1999c3913a8e5a))
* **record:** finish at a start a recovery killed before its copy had its name ([b772285](https://github.com/dchernykh1984/PhotoFinish/commit/b772285eed003497a0c09a3b0f7ec5495afe5056))
* **record:** finish while recording a close that named its times only ([4f96591](https://github.com/dchernykh1984/PhotoFinish/commit/4f96591867dd83058b8fc5d89dafaafd4f8af866))
* **record:** give a cut close's video its name only when its frames are those times ([40851fb](https://github.com/dchernykh1984/PhotoFinish/commit/40851fb0dcd321df41c31663a84dc045bfca63a8))
* **record:** give a recovery killed before its times the times it kept aside ([778e440](https://github.com/dchernykh1984/PhotoFinish/commit/778e440beeced083b2571aeb9f7e6aa66416e0bf))
* **record:** give a video only the name of times written with it ([97e9e92](https://github.com/dchernykh1984/PhotoFinish/commit/97e9e929630466444570508c3ec256badc80297c))
* **record:** judge a recorder by this window's own start and end, guessing no pid ([470196b](https://github.com/dchernykh1984/PhotoFinish/commit/470196b0a9399420fb457a8b2c810fae15284e97))
* **record:** keep a crash read whole though its mark cannot be cleared just then ([51c34cf](https://github.com/dchernykh1984/PhotoFinish/commit/51c34cfb8322208b9e2eeae3be5ee2592ba9b7f2))
* **record:** keep a crash's two files under one stamp when keeping them aside was cut ([5de3d7d](https://github.com/dchernykh1984/PhotoFinish/commit/5de3d7de70ab78d93aef6ad19d35acc81c44519f))
* **record:** keep a dead recorder's end when its restart is refused, not trust its beat ([bf077c7](https://github.com/dchernykh1984/PhotoFinish/commit/bf077c7b70b47c5ca295ba70d30ae2d04d2e2f7a))
* **record:** keep a recovery whose name is held a moment, not drop its copy ([0d468dc](https://github.com/dchernykh1984/PhotoFinish/commit/0d468dcb8d9e1fd4b220906b0925c76c0b2136c4))
* **record:** keep aside only the crash a recovery came from, not a later one ([9d55ac0](https://github.com/dchernykh1984/PhotoFinish/commit/9d55ac072e43714017fcd1e3af1d08578a3a894d))
* **record:** keep aside unread a crash that brought the recorder down as it was read ([e791c31](https://github.com/dchernykh1984/PhotoFinish/commit/e791c31585a0a0787eb0059b1b22ae920c0fb962))
* **record:** keep the frames before a crash's cut, whatever error reading it ends in ([b2e70ea](https://github.com/dchernykh1984/PhotoFinish/commit/b2e70ea3525631f3f9b226df02095626aa2616c8))
* **record:** keep what a crash left as it was until its frames are a segment ([3d147be](https://github.com/dchernykh1984/PhotoFinish/commit/3d147bee6ad52b4cedc69d41971b277b9010450d))
* **record:** know a recovery's source by its times' first line, as the check reads it ([8609699](https://github.com/dchernykh1984/PhotoFinish/commit/8609699716107e4a5b02501702a9eb7b3ea18f22))
* **record:** know this window's recorder by its own pid, through a start the dead one's lock refused ([2efb48e](https://github.com/dchernykh1984/PhotoFinish/commit/2efb48e42b2d9cd784ec4e83b56a2955fda2908d))
* **record:** leave a camera to the recorder whose heartbeat came after this one ended ([b935135](https://github.com/dchernykh1984/PhotoFinish/commit/b93513566a9a60fc172911abf821083c16bc900d))
* **record:** leave out a frame time a kill cut short ([3ef66ab](https://github.com/dchernykh1984/PhotoFinish/commit/3ef66ab8d366d3480af2e070252ae479337f8d4c))
* **record:** leave the camera to a recorder whose heartbeat moved since this one died ([2d52aea](https://github.com/dchernykh1984/PhotoFinish/commit/2d52aeaf241cda8c1d51bd8df8e61910250e111c))
* **record:** let a cut close refused again wait for its name, never split it ([52002b9](https://github.com/dchernykh1984/PhotoFinish/commit/52002b9c27c14c2522f65672a05675de93cf85a2))
* **record:** let a segment's times go when its video will not close ([ce1088f](https://github.com/dchernykh1984/PhotoFinish/commit/ce1088f1f40ab2c9ef0f9cd62e9bda4a98250bc9))
* **record:** list a closed segment though a scanner holds the name it wrote first ([d6d2bb3](https://github.com/dchernykh1984/PhotoFinish/commit/d6d2bb36fa89e2d6b0af079abaff61b751fbc228))
* **record:** list a recovered segment once, by its recovery, not again as missed ([a71a335](https://github.com/dchernykh1984/PhotoFinish/commit/a71a335067d2544c51e3c68150b9a59d3ad152ce))
* **record:** list a recovery named late during a run at once, not at the next start ([7139310](https://github.com/dchernykh1984/PhotoFinish/commit/7139310738242279c0fda1f63dfa2629df2badf1))
* **record:** list a segment recovered while recording as a closed one is, refused or not ([6e103f7](https://github.com/dchernykh1984/PhotoFinish/commit/6e103f72e0f9081b95710342302dd6422838a082))
* **record:** mark a dead recorder's end only once its heartbeat reads, not with 0 ([e4c8e8d](https://github.com/dchernykh1984/PhotoFinish/commit/e4c8e8d90d498fb4cb3876ae5ebabb8f3391cc59))
* **record:** name a recovery left unnamed before the next one, never write it over ([d5787c9](https://github.com/dchernykh1984/PhotoFinish/commit/d5787c9e1e5b90d7439191671091f25806db8bba))
* **record:** name and list a recovery left unnamed as the next segment starts ([71c2f43](https://github.com/dchernykh1984/PhotoFinish/commit/71c2f43fb5314897d9f249d0f57a6969430332df))
* **record:** name no segment over times left alone ([f77b0d4](https://github.com/dchernykh1984/PhotoFinish/commit/f77b0d48d070c2601869370c078c0e6d7d99d99e))
* **record:** never give a segment the name a recovery's copy is still to take ([653494b](https://github.com/dchernykh1984/PhotoFinish/commit/653494bbb283f46b25259dc9c7457c6b81fcc009))
* **record:** never keep a crash aside over one kept in the same millisecond ([673c7d1](https://github.com/dchernykh1984/PhotoFinish/commit/673c7d1afba236abd3b77b24e7f267becaffbb64))
* **record:** note a dead recorder's last beat as read after its end, not before ([be8f223](https://github.com/dchernykh1984/PhotoFinish/commit/be8f2238a8edc74594044e00941cc57abf3fdeb3))
* **record:** pair a crash's video only with its own times, by the stamp written first ([d8b8b5d](https://github.com/dchernykh1984/PhotoFinish/commit/d8b8b5d4ba4116fb115dee916c39520cd276c116))
* **record:** put a segment's frames and times on disk as they are written ([06d882f](https://github.com/dchernykh1984/PhotoFinish/commit/06d882fe60b844755c93276940a50a5d2c4dec6a))
* **record:** read the negative pts of an open GOP's leading frames when recovering ([2a3653b](https://github.com/dchernykh1984/PhotoFinish/commit/2a3653ba0e0d0571374dc1ad6d422748377aa76a))
* **record:** record on past a segment list with bytes that are not ASCII ([1da2d07](https://github.com/dchernykh1984/PhotoFinish/commit/1da2d071d59ffb106af44335f34f1661c3057f56))
* **record:** round a negative pts to ms as the muxer does, half away from zero ([1b7767c](https://github.com/dchernykh1984/PhotoFinish/commit/1b7767ca9cd92c3ebf8ccc2f150e368a36a4bfac))
* **record:** say a full disk met by a recovery and leave the crash for later ([c242d6b](https://github.com/dchernykh1984/PhotoFinish/commit/c242d6b9374a5d2a7465bc24a71520f8324f5076))
* **record:** say starting before seeing to a crash, not the dead run's last word ([b8d8eea](https://github.com/dchernykh1984/PhotoFinish/commit/b8d8eea2dfaedb6281b64ddc7d88d61d4899b7c3))
* **record:** see to what a crash left as a recorder starts, not at its first frame ([ecbec1a](https://github.com/dchernykh1984/PhotoFinish/commit/ecbec1a089460660a4b18b7ffd121e9bbfb51442))
* **record:** show the frames a recorder wrote whole before it died ([42dfb1a](https://github.com/dchernykh1984/PhotoFinish/commit/42dfb1a413eed0f5aed1eea9bd864d515d63881c))
* **record:** show the whole frames of a segment that failed to close ([1406ccd](https://github.com/dchernykh1984/PhotoFinish/commit/1406ccde572f8eb184f4184fc8c4dd3fbb13ce14))
* **record:** start a recorder again 1 s after it dies ([460f2ac](https://github.com/dchernykh1984/PhotoFinish/commit/460f2acc57c23a4c12d05326be22303cadd8c9fd))
* **record:** start a recorder whatever stops what a crash left from being seen to ([165638a](https://github.com/dchernykh1984/PhotoFinish/commit/165638ac7caf6f0a506ba33c5e0a74773f6b8b13))
* **record:** start again at once a recorder that beat and died between two polls ([e306389](https://github.com/dchernykh1984/PhotoFinish/commit/e30638910d151e8abbb1bbaa1a3148e79d101b66))
* **record:** unmark a crash read to an error it said, so no later one goes unread ([7ac17ca](https://github.com/dchernykh1984/PhotoFinish/commit/7ac17ca0749da4dbc533640266476564610c0701))
* **record:** write a crash's stamp only when two renames follow, so none is left stale ([d91a1aa](https://github.com/dchernykh1984/PhotoFinish/commit/d91a1aad8de857a058e0be863809479aec235429))
* **window:** say a refused copy at the next poll, never over a word said once ([1d356ce](https://github.com/dchernykh1984/PhotoFinish/commit/1d356ce1a0dd9850402068491d0e8a473e0c5de9))
* **window:** say a refused copy though the poll fails before it ([c5f6d6b](https://github.com/dchernykh1984/PhotoFinish/commit/c5f6d6b9004feacb1c2b1ea536db1991988ad1fe))


### Performance Improvements

* **output:** find the newest copy from the folder's listing, opening no file on Windows ([251a4da](https://github.com/dchernykh1984/PhotoFinish/commit/251a4da1282ef8e9eecbf8efda8573bab93c1031))
* **output:** keep each output's copies in a folder of its own, looked in alone ([9ac81e5](https://github.com/dchernykh1984/PhotoFinish/commit/9ac81e554448e804ea182aed465f4be4e13e23e7))
* **output:** make no copy of a file the newest copy already holds ([9aa158a](https://github.com/dchernykh1984/PhotoFinish/commit/9aa158a336c542578cadf37a194fbfff3e591a74))
* **output:** work the copies' folder name out once, not at every change ([940d0e0](https://github.com/dchernykh1984/PhotoFinish/commit/940d0e09c6f06ebcd1e1a10ee5cf8d4dcf3bc4c5))
* **record:** look once for what a crash left as each segment begins ([ea4b99f](https://github.com/dchernykh1984/PhotoFinish/commit/ea4b99f5e03ed81deb49fa58b11434a414478cdf))
* **record:** look through a camera's folder once as its recorder starts ([e901bed](https://github.com/dchernykh1984/PhotoFinish/commit/e901bed307dfab6d2b665202a0aa201dc6eeeb75))


### Documentation

* describe the output copies and what a recorder crash costs ([5bfd18f](https://github.com/dchernykh1984/PhotoFinish/commit/5bfd18f3f8fef91677facd24bfad012b773b0bd3))
* **output:** name the growing temp/ copies as the shortcut they are ([74fd4f2](https://github.com/dchernykh1984/PhotoFinish/commit/74fd4f2bec7e7fb0e9fab0c1f4275597cd74de07))
* **specs:** keep a copy of every output change and lose no more video to a crash than it is down ([243eb04](https://github.com/dchernykh1984/PhotoFinish/commit/243eb046e50b55c9d99edb08cc364e6cd3990d5e))

## [0.2.0](https://github.com/dchernykh1984/PhotoFinish/compare/v0.1.0...v0.2.0) (2026-10-30)


### Features

* **align:** align the video with the timing source ([4486bfc](https://github.com/dchernykh1984/PhotoFinish/commit/4486bfcbc9da2391835e6b5742bb68080274d986))
* **analysis:** add the experimental analysis settings ([226cc09](https://github.com/dchernykh1984/PhotoFinish/commit/226cc094e40dcf4f763dd3d6b7ad68501c8b6b1b))
* **analysis:** find riders with a local ONNX detector ([fba91b3](https://github.com/dchernykh1984/PhotoFinish/commit/fba91b38f6bd592473ca9712e6101a22e40a944e))
* **analysis:** index riders by motion that crosses the zone ([6fea04a](https://github.com/dchernykh1984/PhotoFinish/commit/6fea04a2581281bcc521b44adc21ce432585f225))
* **analysis:** suggest crossings where a rider crosses the finish line ([6c8206c](https://github.com/dchernykh1984/PhotoFinish/commit/6c8206c190c96f53c98d474351c94ba4b3a66824))
* **cameras:** connect USB, RTSP, RTMP and file cameras with the owner's presets ([0d75b78](https://github.com/dchernykh1984/PhotoFinish/commit/0d75b786e000acc241ebeeb299e6dbc5c2e965e2))
* **cameras:** open a camera's own recording after the race ([1d73fc4](https://github.com/dchernykh1984/PhotoFinish/commit/1d73fc42a491bf0ab737dc821694272fbafd2c9a))
* **cameras:** show several cameras at one moment and align them on a shared event ([ce870b4](https://github.com/dchernykh1984/PhotoFinish/commit/ce870b479acff133f1147a3c2a203ad01a2ab099))
* **input:** take new chronometer lines and hold back changed ones ([0cda485](https://github.com/dchernykh1984/PhotoFinish/commit/0cda48587cfa43d63630c48a71ab8e80eb9da79f))
* **lines:** read and write crossing lines and times ([fcb34b3](https://github.com/dchernykh1984/PhotoFinish/commit/fcb34b3b0f6d048fa1773fb3c356788e9500d580))
* **output:** keep the referee's crossings in their file with a journal ([9051232](https://github.com/dchernykh1984/PhotoFinish/commit/905123296447dc33b7a21c7d5c8bbd24eaa26154))
* **precision:** pick a time between two frames on the zoomed timeline ([642ecb8](https://github.com/dchernykh1984/PhotoFinish/commit/642ecb8d11fab1fc21f78c3378bcb4048889559e))
* **precision:** read a crossing time between two frames like a caliper ([6fcdd26](https://github.com/dchernykh1984/PhotoFinish/commit/6fcdd26bb4f5db9624ab1ee90f4f6a7c32648509))
* **record:** keep recording when the window is gone ([fb50957](https://github.com/dchernykh1984/PhotoFinish/commit/fb50957893d2923446f844092c13ea7ff57ea7ad))
* **record:** run a camera's recorder as a process of its own ([019c4b3](https://github.com/dchernykh1984/PhotoFinish/commit/019c4b3c24dd9bd1b0bd913ef451c6f771121b2d))
* **record:** write a camera in short segments with each frame's time ([6515f36](https://github.com/dchernykh1984/PhotoFinish/commit/6515f3650de1cbf5f380febb3a576fd2d49ef9f5))
* **session:** keep the session next to the program ([77b324b](https://github.com/dchernykh1984/PhotoFinish/commit/77b324b321321de4530312c2e08d2e58b4c86c24))
* **video:** index recorded frames and decode any of them ([ce12058](https://github.com/dchernykh1984/PhotoFinish/commit/ce1205804831d939e7bc62ff8720ee766ecd2abd))
* **window:** add a crossing at the current frame from the keyboard ([26bbce5](https://github.com/dchernykh1984/PhotoFinish/commit/26bbce5a8ca9f942e61bc571e74603f58f093cc3))
* **window:** correct a crossing's time or number and remove a false one ([379197e](https://github.com/dchernykh1984/PhotoFinish/commit/379197eb97501c5a587bd0f405da3186f91ac1b7))
* **window:** jump to the next and previous rider ([589eebc](https://github.com/dchernykh1984/PhotoFinish/commit/589eebca258aee04e9feee50618f51d9c4bdfa4c))
* **window:** scroll a camera while it records ([d44ac20](https://github.com/dchernykh1984/PhotoFinish/commit/d44ac20a7691e080c459da14915b915bd12ffe78))
* **window:** show the input and output lists at the video's time ([f205a74](https://github.com/dchernykh1984/PhotoFinish/commit/f205a74d70672374c44a61333a88f472608999af))


### Bug Fixes

* **analysis:** look at a segment earlier than the last from its start, not skip it ([0e903e9](https://github.com/dchernykh1984/PhotoFinish/commit/0e903e9c4df49772ebd2b7240e33a5a7c05d7896))
* **analysis:** offer a crossing suggested twice only once ([ed18dfb](https://github.com/dchernykh1984/PhotoFinish/commit/ed18dfb5a80697a8e855ac02bb23658a1d6adb98))
* **analysis:** retry a segment in order and afresh, and suggest riders a millisecond apart singly ([0ece5a2](https://github.com/dchernykh1984/PhotoFinish/commit/0ece5a2e1615295fb1e6c31bf27d9a5d6f145f8a))
* **analysis:** try a segment held a moment again instead of passing it over ([49a856d](https://github.com/dchernykh1984/PhotoFinish/commit/49a856df5e5b004819248d28738721666bdbdbc2))
* **cameras:** ask for a picture size's width and height both ([e6f968a](https://github.com/dchernykh1984/PhotoFinish/commit/e6f968a2268a83d582f9f67bf3ebaafc82819e8d))
* **cameras:** refuse a USB camera where this build cannot capture one ([a539d13](https://github.com/dchernykh1984/PhotoFinish/commit/a539d13ef69974546a9575c1e86472d315246c56))
* **index:** give up a segment whose frame times stay unreadable, and say so ([af7c68d](https://github.com/dchernykh1984/PhotoFinish/commit/af7c68d0e1eb6042a167d3aa9ac605fdc3e78e9a))
* **index:** step over a gap in the recording and read only the gaps noted since the last poll ([d1e3f44](https://github.com/dchernykh1984/PhotoFinish/commit/d1e3f449c8deb10085040ef6afc5cc320d7be0ed))
* **input:** hold back an edit of every line taken instead of taking it as a new file ([458c27f](https://github.com/dchernykh1984/PhotoFinish/commit/458c27f90ec072001c322b88ddc1cc2ea25151d4))
* **input:** judge a file at rest by this computer's clock and read a shortened one only then ([0635786](https://github.com/dchernykh1984/PhotoFinish/commit/0635786128795e025b0818df17bd05095965a44d))
* **input:** show lines and copies as done when only their journal entries failed ([d26e4d6](https://github.com/dchernykh1984/PhotoFinish/commit/d26e4d6c041a9b7aa2e4608c898b60624f60b499))
* **input:** take a last line left without its line break once the file rests ([5db4d1b](https://github.com/dchernykh1984/PhotoFinish/commit/5db4d1bddb9959f4d967fd9425a2100fec86ef94))
* **input:** take a rider's next lap as a crossing, not as an edit of a lap deleted ([6b7a333](https://github.com/dchernykh1984/PhotoFinish/commit/6b7a333b72deacfc401f89108c94871aade1f4d2))
* keep a drawn line or zone only when it has extent and record whatever the window has ([1f3f1fe](https://github.com/dchernykh1984/PhotoFinish/commit/1f3f1fe48ce6e506f887301060fb6712bbe711b7))
* **output:** bring a crash-left file up to the state, back up an outside version once, read first ([8aa34ef](https://github.com/dchernykh1984/PhotoFinish/commit/8aa34efd43bab110e6e8d209b03186296838d52f))
* **output:** journal a change once written and take back the state of one that was not ([cbd10a5](https://github.com/dchernykh1984/PhotoFinish/commit/cbd10a5546e4c2cb79e7ffc78174e8552fe96c06))
* **output:** journal adopted and replaced lines, reread a held file and follow the input faster ([b26925e](https://github.com/dchernykh1984/PhotoFinish/commit/b26925ebabfa69e032b50228b66885ee1a90da02))
* **output:** journal an outside version once written back and report a refused journal as written ([2859541](https://github.com/dchernykh1984/PhotoFinish/commit/2859541475fcd51e09f6a9c5b004f53b4eaad8fd))
* **output:** keep an outside version once, open despite a refused journal, keep each line's bytes ([9ecbac3](https://github.com/dchernykh1984/PhotoFinish/commit/9ecbac35122620ea357caf2c86848ae7cb843e5f))
* **output:** tell a change written but not journaled from one not written ([eaefa40](https://github.com/dchernykh1984/PhotoFinish/commit/eaefa4022d5ed2fca62976192787eedbab12f104))
* **output:** trust the journal after a broken state, keep equal times in place, place lines faster ([c7ff4ba](https://github.com/dchernykh1984/PhotoFinish/commit/c7ff4badf4c2ed1281733cf96f8949978bb3d4f6))
* **output:** undo failed changes, keep removed crossings out, relink lines and complete short ones ([f8f4217](https://github.com/dchernykh1984/PhotoFinish/commit/f8f4217efd309e315a94508ad2fd6ddb7396d4d7))
* **record:** count the last segment in the heartbeat a stop leaves ([4ce253b](https://github.com/dchernykh1984/PhotoFinish/commit/4ce253b7ad081b20391091cd43a4c35032adf66e))
* **record:** keep a segment that failed to close, and follow the segment list for video and analysis ([7586bd7](https://github.com/dchernykh1984/PhotoFinish/commit/7586bd7f256f6f1612a11e2f963c6683d7bcf4db))
* **record:** keep time and the heartbeat right through clock drift, a clock set back and a low disk ([93de8d8](https://github.com/dchernykh1984/PhotoFinish/commit/93de8d8363deaf7f10434c440c96bc66f277bad9))
* **record:** record through a drifting clock and a failed close, and call a recorder gone less soon ([e4245f8](https://github.com/dchernykh1984/PhotoFinish/commit/e4245f8e70d062ec6f9eca0e83dc7abb99f9b8a7))
* **record:** report and retry a recorder that cannot start, and tidy the segment code ([033acf4](https://github.com/dchernykh1984/PhotoFinish/commit/033acf4d920684687804c5f29e348044b1487e46))
* **record:** restart after a stop withdrawn too late, find file cameras from any folder, list faster ([63183dc](https://github.com/dchernykh1984/PhotoFinish/commit/63183dcf0a1091c9e996af54c5cbbda2fb1dd494))
* **record:** retry a recorder despite an old end in its heartbeat and list a refused segment next ([8f1cfc9](https://github.com/dchernykh1984/PhotoFinish/commit/8f1cfc972aca1cb467a66ec478afe8c403fc7afa))
* **record:** start a frozen recorder as its own instance and report a full disk in place ([402934a](https://github.com/dchernykh1984/PhotoFinish/commit/402934acc8ae8f6635c57103ed3f01b5476b5367))
* **record:** time frames on the computer's clock after a sleep and withdraw a stop not yet heard ([09692f5](https://github.com/dchernykh1984/PhotoFinish/commit/09692f55f3b1711d5285af3b495bbf38f7c2ca2e))
* **session:** write the session past a reader's moment and read one being replaced again ([8bf25a3](https://github.com/dchernykh1984/PhotoFinish/commit/8bf25a3fbaa3be29cfbe5e718cbf5d79041ee588))
* start a line appended after one a kill cut short on a line of its own ([b546204](https://github.com/dchernykh1984/PhotoFinish/commit/b54620456c7237be4fb5dcca748f00d98829e84b))
* **video:** read a recording on its own thread, seek far ahead and pass over empty segments ([c7eca8f](https://github.com/dchernykh1984/PhotoFinish/commit/c7eca8f5a62b075b678b7e2a7ccbf11237ea7fce))
* **view:** show padded frames, answer every frame asked for and seek on a click in a gap ([ba2e03c](https://github.com/dchernykh1984/PhotoFinish/commit/ba2e03cd382bd96b69392b392d5bcc67966d57fd))
* **window:** ask for a frame by itself and show no span for a camera without frames ([929fd8f](https://github.com/dchernykh1984/PhotoFinish/commit/929fd8fab50334098cf1d2dee301706261cf86ec))
* **window:** correct the crossing chosen as lines move and keep a suggestion whose write failed ([b2d2697](https://github.com/dchernykh1984/PhotoFinish/commit/b2d2697cb42934703b0618d0723887866d5ea1b2))
* **window:** give a caliper time to the number typed and time nothing on a frame on its way ([8d20a3d](https://github.com/dchernykh1984/PhotoFinish/commit/8d20a3dd996e8ea0f414d6ca61e18ca31219649a))
* **window:** hand the analyser a line drawn anew and drop one half drawn on a camera switch ([7c21823](https://github.com/dchernykh1984/PhotoFinish/commit/7c218238e150c14c0c4d5f5083093e7f3db7a2b2))
* **window:** keep the moment and the frames shown when the camera changes or frames are sorted ([f6b6905](https://github.com/dchernykh1984/PhotoFinish/commit/f6b69059090bae73bd6cdc6126b4a23d5800ef98))
* **window:** leave L to the number typed and go live with End ([9c77ba7](https://github.com/dchernykh1984/PhotoFinish/commit/9c77ba7c6bced3ee2a77c90fe62079f6c361d24b))
* **window:** let an ended analyser's process object go ([95750ae](https://github.com/dchernykh1984/PhotoFinish/commit/95750aecebf04b3a5868f09d466675a7544fcc09))
* **window:** open held outputs and unlisted file cameras, align on settled frames, report versions ([e23e16a](https://github.com/dchernykh1984/PhotoFinish/commit/e23e16a6ea8defc948745ef31d021d2d7a5bc039))
* **window:** say a decision on a suggestion the disk refuses, the suggestion gone ([dedf050](https://github.com/dchernykh1984/PhotoFinish/commit/dedf050119fb1aea4ce71252b3c853939e1cc328))
* **window:** say a time offered to a line removed meanwhile, never drop it unsaid ([2d41b19](https://github.com/dchernykh1984/PhotoFinish/commit/2d41b19db8b4e98f0748308d7e9a4d37493b7d3b))
* **window:** send an analyser's error output nowhere instead of keeping it unread ([a360664](https://github.com/dchernykh1984/PhotoFinish/commit/a360664a1586a41a29b86ade858cb417ce5eb21f))
* **window:** show decoded frames on the window's thread and follow the very output line chosen ([f1f5c7d](https://github.com/dchernykh1984/PhotoFinish/commit/f1f5c7d347de80a69587c3feda8c16262ad598d5))
* **window:** show no stale frame while one is decoded and keep the suggestion chosen on a redraw ([08c0380](https://github.com/dchernykh1984/PhotoFinish/commit/08c0380a94e2fe38a573c29dfbd24d2077a54829))
* **window:** start a new shared event once every camera is aligned or the last is stale ([08eae90](https://github.com/dchernykh1984/PhotoFinish/commit/08eae902b581dde17540bc51b40d11531da24a9b))
* **window:** stop a removed camera's analyser ([bb20de5](https://github.com/dchernykh1984/PhotoFinish/commit/bb20de50ef0470e067e448b07922266301271e66))
* **window:** stop an analyser without waiting for it, and start the next after it ends ([5a829f4](https://github.com/dchernykh1984/PhotoFinish/commit/5a829f4929012f30f687f2ae6d9863474c2d9572))


### Performance Improvements

* build a model's anchor grid once and look this computer's address up once a dialog ([010de28](https://github.com/dchernykh1984/PhotoFinish/commit/010de2887b0ac309fe060b0a1f76f684c574d730))
* **output:** keep the lines' fields for an undo without copying them deeply ([2233a6f](https://github.com/dchernykh1984/PhotoFinish/commit/2233a6f3e59c83902cd63801728cb933e611201a))
* **video:** grow the frame arrays by doubling and draw the offset, not a copy ([9b93345](https://github.com/dchernykh1984/PhotoFinish/commit/9b93345325ff6ee9aed42d865bd12445d9e86881))


### Documentation

* allow sub-frame times and require recording to outlive the editor ([025ba28](https://github.com/dchernykh1984/PhotoFinish/commit/025ba28709e9cda421dd0b10e7fc58f1ebd97736))
* describe the experimental rider finding ([515f2af](https://github.com/dchernykh1984/PhotoFinish/commit/515f2afbe4f9286dcf9299a865fe5e7d64691360))
* describe the live editor ([161b973](https://github.com/dchernykh1984/PhotoFinish/commit/161b973fef0b8bac400dee3423e1b30686e31341))
* plan the live editor and the experimental rider finding ([b9a6545](https://github.com/dchernykh1984/PhotoFinish/commit/b9a65451a1c365b37721b93fdad7a1b1b4999b2c))
* respecify the video tool as a live recorder and specify rider finding as an experiment ([50e5681](https://github.com/dchernykh1984/PhotoFinish/commit/50e5681c566fd48a587355ed09a6e12c513b00bc))
* settle the live editor and rider finding specs and plans after three review cycles ([8267974](https://github.com/dchernykh1984/PhotoFinish/commit/8267974199b164ac4e88e88c8770ac306e8c7313))

## 0.1.0 (2026-10-28)


### Documentation

* adopt a constitution for spec-first changes ([bceabef](https://github.com/dchernykh1984/PhotoFinish/commit/bceabef278c618675333dabbf2ee2da695066067))
* describe how to download, run and develop PhotoFinish ([c23759d](https://github.com/dchernykh1984/PhotoFinish/commit/c23759d7cbdbc299e59ea025166eebb7487faf7c))
* describe the time field the way the chronometers actually write it ([78ea945](https://github.com/dchernykh1984/PhotoFinish/commit/78ea94572f828b03515f7ec53b6e6e3f54e51389))
* key a correction by the occurrence of its line as well ([0ec087b](https://github.com/dchernykh1984/PhotoFinish/commit/0ec087b1d3a2ea6e1c7ebca06bc6f049f65e8eb4))
* name the summer-time option wherever the spec says standard time ([fd58c87](https://github.com/dchernykh1984/PhotoFinish/commit/fd58c87a75279c9c6188dfe9818a4364a771f454))
* note that the first ASCII check on a cold pre-commit cache clones the hook repos ([7d86657](https://github.com/dchernykh1984/PhotoFinish/commit/7d86657fb1fd4ed15253d8ab7ecaccb3cd35c208))
* point macOS users to clearing the quarantine flag, not to moving the app ([c396fc0](https://github.com/dchernykh1984/PhotoFinish/commit/c396fc0d24bca46d7edbe7b9930f2554438d9501))
* process Qt events in the layout snippet without a local named app ([73300b2](https://github.com/dchernykh1984/PhotoFinish/commit/73300b29f944b2c56d6710e1dc472499038be6f6))
* require the journal to name the frame and tell repeated lines apart ([2314b6b](https://github.com/dchernykh1984/PhotoFinish/commit/2314b6b05fee89c2823fa27060c49aef69259ea8))
* say that milliseconds are always three digits in the time field ([d277ba2](https://github.com/dchernykh1984/PhotoFinish/commit/d277ba2989c5ab37065ba455ea43907991450c7d))
* say the edit hooks use the installed ruff and need a sync after a lock change ([1ae837a](https://github.com/dchernykh1984/PhotoFinish/commit/1ae837a2aaac62927e009b6b620419ff146c3def))
* specify refining crossing times from video ([ab68c47](https://github.com/dchernykh1984/PhotoFinish/commit/ab68c4701efb4e470248605653301d8f96727e94))
* state that the chronometers keep local standard time ([09de169](https://github.com/dchernykh1984/PhotoFinish/commit/09de169431cd3af459dad9ead408d1707eff60a7))
* wait for the release PR's lock commit before merging it ([a302637](https://github.com/dchernykh1984/PhotoFinish/commit/a30263722de92f48f79a633de6533c539752d216))
* warn that a still-quarantined app runs from a read-only copy on macOS ([ff60050](https://github.com/dchernykh1984/PhotoFinish/commit/ff60050cfbdc36d8039515d39e08d8a413bb4ee5))
