import React from 'react';
import {Composition, registerRoot, Still} from 'remotion';
import {Nim, NimStoneCloseup} from './Nim';

const NimRoot = () => <>
  <Composition id="NimReview" component={Nim} width={1080} height={1920} fps={30} durationInFrames={1044}/>
  <Composition id="NimCinema" component={Nim} width={1080} height={1920} fps={60} durationInFrames={11040}/>
  <Still id="NimStoneCloseup" component={NimStoneCloseup} width={1080} height={1920}/>
</>;

registerRoot(NimRoot);
