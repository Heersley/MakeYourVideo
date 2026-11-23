import {AbsoluteFill, Composition, registerRoot} from 'remotion';
import {Diagram} from './src/Diagram';

function StudioScene() {
  return <AbsoluteFill style={{backgroundColor: '#060709', alignItems: 'center', justifyContent: 'center'}}>
    <div style={{width: 546, height: 573}}><Diagram/></div>
  </AbsoluteFill>;
}

registerRoot(() => <Composition id="Diameter" component={StudioScene}
  width={720} height={1280} fps={30} durationInFrames={450}/>);
