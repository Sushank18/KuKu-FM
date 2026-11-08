@echo off
mkdir clips 2>nul
mkdir thumbnails 2>nul

rem --- Episode 1 Promo & Thumbnail ---
ffmpeg -y -ss 00:01:15.000 -i "raw_videos/episode_1.mp4" -t 00:00:35.800 -c:v libx264 -crf 18 -preset fast -c:a aac "clips/promo_ep1_75s_to_110s.mp4"
ffmpeg -y -ss 00:01:20.200 -i "raw_videos/episode_1.mp4" -vframes 1 -q:v 2 "thumbnails/thumb_ep1_80s.jpg"

rem --- Episode 2 Promo & Thumbnail ---
ffmpeg -y -ss 00:00:00.000 -i "raw_videos/episode_2.mp4" -t 00:00:44.800 -c:v libx264 -crf 18 -preset fast -c:a aac "clips/promo_ep2_0s_to_44s.mp4"
ffmpeg -y -ss 00:00:01.250 -i "raw_videos/episode_2.mp4" -vframes 1 -q:v 2 "thumbnails/thumb_ep2_1s.jpg"

rem --- Episode 3 Promo & Thumbnail ---
ffmpeg -y -ss 00:01:19.300 -i "raw_videos/episode_3.mp4" -t 00:00:56.200 -c:v libx264 -crf 18 -preset fast -c:a aac "clips/promo_ep3_79s_to_135s.mp4"
ffmpeg -y -ss 00:01:22.500 -i "raw_videos/episode_3.mp4" -vframes 1 -q:v 2 "thumbnails/thumb_ep3_82s.jpg"

rem --- Episode 4 Promo & Thumbnail ---
ffmpeg -y -ss 00:01:54.800 -i "raw_videos/episode_4.mp4" -t 00:00:36.600 -c:v libx264 -crf 18 -preset fast -c:a aac "clips/promo_ep4_114s_to_151s.mp4"
ffmpeg -y -ss 00:01:55.800 -i "raw_videos/episode_4.mp4" -vframes 1 -q:v 2 "thumbnails/thumb_ep4_115s.jpg"

rem --- Episode 5 Promo & Thumbnail ---
ffmpeg -y -ss 00:00:46.000 -i "raw_videos/episode_5.mp4" -t 00:00:55.500 -c:v libx264 -crf 18 -preset fast -c:a aac "clips/promo_ep5_46s_to_101s.mp4"
ffmpeg -y -ss 00:00:52.900 -i "raw_videos/episode_5.mp4" -vframes 1 -q:v 2 "thumbnails/thumb_ep5_52s.jpg"
